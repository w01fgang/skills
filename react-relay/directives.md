# Relay GraphQL Directives

Reference for every directive Relay understands. Grouped by use case. Hooks-only
(no legacy `createFragmentContainer` / `createRefetchContainer` directives).

All examples assume `relay-compiler` and the React hooks runtime (`useFragment`,
`usePreloadedQuery`, `useLazyLoadQuery`, `usePaginationFragment`,
`useRefetchableFragment`, `useMutation`, `useSubscription`).

---

## Fragment definition

### `@argumentDefinitions`

Declares local arguments (or provided variables) on a fragment.

**Signature**

```graphql
@argumentDefinitions(
  name: { type: "TypeName", defaultValue?: Any, provider?: "./providerPath" }
  ...
)
```

**Where** — fragment definition (after `fragment Foo on Type`).

**Example**

```graphql
fragment UserCard_user on User
  @argumentDefinitions(
    size: { type: "Int", defaultValue: 64 }
    withPosts: { type: "Boolean!", defaultValue: false }
    viewerLocale: { type: "String!", provider: "./LocaleProvider.relayprovider" }
  ) {
  name
  avatar(size: $size) { url }
  posts @include(if: $withPosts) { id }
  greeting(locale: $viewerLocale)
}
```

```tsx
const user = useFragment(graphql`...UserCard_user @arguments(size: 128, withPosts: true)`, ref);
```

**Pitfalls**
- `type:` is a string; include the trailing `!` for non-null.
- A `provider` module must export `{ get(): T }`; providers cannot have defaults.
- Types must match the usage site; compiler errors surface at build time.

### `@arguments`

Passes values for a fragment's `@argumentDefinitions` at a spread site.

**Signature** — `@arguments(name: Value, ...)`

**Where** — fragment spread.

**Example**

```graphql
query ProfileQuery($id: ID!) {
  user(id: $id) {
    ...UserCard_user @arguments(size: 256, withPosts: true)
  }
}
```

**Pitfalls**
- Missing an argument without a default triggers a compile error.
- You cannot pass `@arguments` to a fragment that lacks `@argumentDefinitions`.

### `@refetchable`

Generates a query that refetches the fragment. Unlocks
`useRefetchableFragment` and `usePaginationFragment`.

**Signature**

```graphql
@refetchable(
  queryName: String!
  directives: [String!]       # directives to copy to the generated query
  preferFetchable: Boolean    # prefer @fetchable types over Node when both apply
)
```

**Where** — fragment on `Query`, `Viewer`, or any type implementing `Node` (or
annotated `@fetchable`).

**Example**

```graphql
fragment Feed_viewer on Viewer
  @refetchable(queryName: "FeedRefetchQuery") {
  posts(first: $count) @connection(key: "Feed_posts") {
    edges { node { id ...PostRow_post } }
  }
}
```

```tsx
const [data, refetch] = useRefetchableFragment(graphql`...Feed_viewer`, viewer);
refetch({ count: 20 }, { fetchPolicy: "network-only" });
```

**Pitfalls**
- The fragment must have a single refetch identifier (`id` for `Node`, none for
  `Query`/`Viewer`).
- Name collisions with other generated queries — keep `queryName` unique.

### `@inline`

Reads a fragment's data imperatively outside React render.

**Where** — fragment definition.

**Example**

```graphql
fragment logPayload_user on User @inline { id locale }
```

```ts
import { readInlineData } from "react-relay";
function logUser(userRef) {
  const data = readInlineData(graphql`...logPayload_user`, userRef);
  analytics.log("user", data);
}
```

**Pitfalls**
- Cannot contain `@defer`, `@stream`, or `@module`.
- Not a substitute for `useFragment` — component render must still subscribe.

### `@relay(plural: Boolean)`

Marks a fragment as expecting an array of refs.

```graphql
fragment Avatars_users on User @relay(plural: true) {
  id
  avatar { url }
}
```

```tsx
const users = useFragment(graphql`...Avatars_users`, refs /* User[] */);
```

### `@relay(mask: false)`

Disables data masking so the parent sees the child's selections directly.
Rarely needed; prefer `@inline`.

```graphql
...Parent_user @relay(mask: false)
```

On a fragment definition, `@relay(mask: false)` changes the generated types so
the fragment is usable only through unmasked spreads.

**Pitfalls**
- Breaks the encapsulation guarantee. Do not combine with `@arguments`.

---

## Connection & pagination

### `@connection`

Registers a Relay connection for `usePaginationFragment`, store updaters, and
declarative mutation directives.

**Signature**

```graphql
@connection(
  key: String!
  filters: [String!]          # arg names that differentiate connections
  handler: String              # custom ConnectionHandler
  dynamicKey_UNSTABLE: String  # advanced, runtime-keyed connections
)
```

**Where** — a connection field (anything returning `XxxConnection`) inside a
`@refetchable` fragment (for pagination).

**Example**

```graphql
fragment Feed_viewer on Viewer
  @refetchable(queryName: "FeedPaginationQuery") {
  posts(first: $count, after: $cursor, category: $category)
    @connection(key: "Feed_posts", filters: ["category"]) {
    edges { node { id ...PostRow_post } }
  }
}
```

```tsx
const { data, loadNext, hasNext, isLoadingNext } = usePaginationFragment(
  graphql`...Feed_viewer`,
  viewerRef,
);
```

**Pitfalls**
- `first`/`last` and `after`/`before` must be variables, not literals.
- `filters` defaults to every non-pagination arg; narrow it to avoid cache
  fragmentation.
- Each `key` must be unique per component type.

---

## Declarative mutation updates

All four operate on **mutation, subscription or query response fields** and need a
`connections: [ID!]!` variable populated from `__id` on the parent connection.

```graphql
query Example {
  viewer {
    posts(first: 10) @connection(key: "Feed_posts") {
      __id   # feed this into the mutation as a connection ID
      edges { node { id } }
    }
  }
}
```

### `@appendEdge` / `@prependEdge`

Appends or prepends an edge payload to each listed connection.

**Signature** — `@appendEdge(connections: [ID!]!)`, same for `@prependEdge`.

**Where** — a response field of edge type (or `[Edge]`).

```graphql
mutation AddPost($input: AddPostInput!, $connections: [ID!]!) {
  addPost(input: $input) {
    postEdge @prependEdge(connections: $connections) {
      cursor
      node { id ...PostRow_post }
    }
  }
}
```

```tsx
commit({
  variables: { input, connections: [feedConnectionId] },
});
```

### `@appendNode` / `@prependNode`

Same placement semantics, but the server returns a node and Relay wraps it in a
synthesized edge.

**Signature**

```graphql
@appendNode(connections: [ID!]!, edgeTypeName: String!)
```

**Where** — a response field of node type.

```graphql
mutation AddPost($input: AddPostInput!, $connections: [ID!]!) {
  addPost(input: $input) {
    post @appendNode(connections: $connections, edgeTypeName: "PostEdge") {
      id ...PostRow_post
    }
  }
}
```

**Pitfalls**
- `edgeTypeName` must exactly match your schema's edge type.
- The selected node must include `id` so Relay can build the edge.

### `@deleteEdge`

Removes edges whose node IDs are listed in the payload from each connection.

**Signature** — `@deleteEdge(connections: [ID!]!)`

**Where** — a response field of type `ID` or `[ID!]`.

```graphql
mutation DeletePosts($input: DeletePostsInput!, $connections: [ID!]!) {
  deletePosts(input: $input) {
    deletedPostIds @deleteEdge(connections: $connections)
  }
}
```

### `@deleteRecord`

Removes the record itself from the Relay store (and from any connection that
holds it).

**Signature** — `@deleteRecord` (no args).

**Where** — a response field of type `ID` (the ID of the record to delete).

```graphql
mutation DeleteUser($input: DeleteUserInput!) {
  deleteUser(input: $input) {
    deletedUserId @deleteRecord
  }
}
```

**Pitfalls**
- The field must literally be an ID scalar. Wrap object responses accordingly.
- `@deleteRecord` purges globally; use `@deleteEdge` when you only want to
  detach from specific connections.

---

## Streaming & defer

### `@defer`

Splits a fragment spread out of the initial payload; the server streams it as a
follow-up. Relay suspends until the deferred chunk arrives (or renders with
partial data in conjunction with React Suspense).

**Signature** — `@defer(label: String, if: Boolean = true)`

**Where** — fragment spread.

```graphql
query ProfileQuery($id: ID!) {
  user(id: $id) {
    name
    ...ExpensiveDetails_user @defer(label: "details", if: $showDetails)
  }
}
```

```tsx
function Profile({ queryRef }) {
  const data = usePreloadedQuery(query, queryRef);
  return (
    <>
      <h1>{data.user.name}</h1>
      <Suspense fallback={<Spinner />}>
        <Details user={data.user} />
      </Suspense>
    </>
  );
}
```

**Pitfalls**
- Requires a server that supports GraphQL incremental delivery (`multipart/mixed`
  or SSE).
- `label` must be unique per operation.
- Cannot appear inside `@inline` fragments.

### `@stream`

Streams list items progressively. Can be used directly on any list field.

**Signature** — `@stream(label: String, initial_count: Int!, if: Boolean = true)`

**Where** — list field selection.

```graphql
query SearchQuery($term: String!) {
  search(term: $term) {
    results @stream(label: "search_results", initial_count: 5) {
      id ...ResultRow_result
    }
  }
}
```

### `@stream_connection`

`@connection` plus streaming. Used with `usePaginationFragment`; items past
`initial_count` arrive in follow-up payloads.

**Signature** — accepts every `@connection` argument plus
`initial_count: Int = 0` and `if: Boolean = true`.

```graphql
fragment Friends_user on User
  @refetchable(queryName: "FriendsPaginationQuery") {
  friends(first: $count, after: $cursor)
    @stream_connection(key: "Friends_user_friends", initial_count: 10) {
    edges { node { id name } }
  }
}
```

**Pitfalls**
- Do not combine `@connection` and `@stream_connection` on the same field.
- `initial_count` does not cap the total — only the size of the first payload.

---

## Error handling & nullability

### `@required`

Bubbles null up if the annotated field is null.

**Signature** — `@required(action: NONE | LOG | THROW | DANGEROUSLY_THROW_ON_SEMANTICALLY_NULLABLE_FIELD)`

**Where** — field selection.

```graphql
fragment UserEmail_user on User {
  email @required(action: LOG)
  profile @required(action: LOG) {
    bio @required(action: THROW)
  }
}
```

| `action` | Behavior |
|----------|----------|
| `NONE`   | Parent linked field becomes null |
| `LOG`    | Same as `NONE` plus a `missing_required_field.log` event to `relayFieldLogger` |
| `THROW`  | Reading the fragment throws |
| `DANGEROUSLY_THROW_ON_SEMANTICALLY_NULLABLE_FIELD` | Same as `THROW`, allowed on nullable fields when the `disallow_required_action_throw_on_semantically_nullable_fields` feature flag is on. A migration aid; avoid new uses. |

**Pitfalls**
- `@required` applies to the reader, not the network — the field is still
  fetched.
- If every selection on a parent object is `@required(THROW)`, the parent is
  effectively non-null when reading.
- A `@required` field cannot have an `action` less severe than its `@required`
  parent (`NONE` < `LOG` < `THROW`).
- Inside a `@connection`, `@required` on the `node` field or on its direct
  child fields is a compiler error.

### `@throwOnFieldError`

Promotes GraphQL field errors in the response to thrown exceptions at read
time, and makes selections semantically non-null in generated types. It also
throws when data is missing from the store.

**Where** — queries and fragments.

```graphql
fragment Card_user on User @throwOnFieldError {
  name
  followerCount
}
```

```tsx
// data.name is typed as string (not string | null)
const data = useFragment(graphql`...Card_user`, ref);
```

**Pitfalls**
- Only safe for fields your UI genuinely cannot render without. Use `@catch` to
  recover granularly.

### `@catch`

Catches field errors into a result wrapper instead of throwing.

**Signature** — `@catch(to: RESULT | NULL)` (default `RESULT`).

**Where** — fields, fragments, queries, mutations, aliased inline fragments.
Relay v21 also accepts `@catch` on `@connection` fields and on client edge
fields.

```graphql
fragment Card_user on User @throwOnFieldError {
  name
  followerCount @catch
  latestPost @catch(to: NULL) { title }
}
```

```tsx
const { name, followerCount, latestPost } = useFragment(...);
// followerCount: { ok: true; value: number } | { ok: false; errors: [...] }
// latestPost:    { title: string } | null
```

**Pitfalls**
- `RESULT` changes the shape of the generated type — expect a discriminated
  union.
- `@catch` at the query root is the typical escape hatch from
  `@throwOnFieldError`.
- `@catch` and `@throwOnFieldError` cover the fields of their own query,
  fragment or mutation. Fields of a spread fragment need their own directive.

### `@semanticNonNull`

Schema-side directive marking fields as *semantically* non-null: the field can
return null only in error cases. Relay's generated TypeScript types treat the
field as non-null so you don't have to null-check it at read sites, while the
runtime still handles error cases gracefully (usually via `@throwOnFieldError`
or `@catch` at an ancestor selection).

**Signature** — `@semanticNonNull(levels: [Int] = [0])` (levels applies for list
types — specify which list levels are semantically non-null).

**Where it applies** — schema definition (on field definitions), not in client
queries.

**Example** (schema):

```graphql
type User {
  name: String @semanticNonNull
  avatarUrl: String @semanticNonNull
  friends: [User] @semanticNonNull(levels: [0, 1])
}
```

In client code, generated types expose `user.name` as `string`, not `string | null`.
Must be combined with `@throwOnFieldError` (or a `@catch`) on the reader so
errors surface rather than crash at runtime.

### `@alias`

Aliases a fragment spread or inline fragment so it reads as a nested object;
used to make conditional / type-refined fragments null-safe.

**Signature** — `@alias(as: String)`. `as` is optional. The default alias is
the fragment name for a fragment spread and the type name for an inline
fragment. An inline fragment with no type condition needs `as`.

**Where** — fragment spread, inline fragment.

```graphql
fragment Feed_viewer on Viewer {
  actor {
    ... on User @alias(as: "asUser") {
      ...UserCard_user
    }
  }
}
```

```tsx
if (data.actor.asUser != null) {
  <UserCard user={data.actor.asUser} />;
}
```

**Pitfalls**
- Without `@alias`, inline fragments on non-matching types leave fields
  `undefined` rather than exposing a typed `null`.

---

## Resolvers

Resolver tags live in **docblock comments** on exported TS/JS functions and
types in files the Relay compiler scans. The compiler reads a docblock only
when it has a `@relayType` or `@relayField` tag. Relay v20 and earlier used the
single tag `@RelayResolver`; `relay-compiler codemod fix-all` migrates it.

### `@relayField` and `@relayType`

`@relayField` defines a field. `@relayType` defines a client type.

**Field form**

```ts
/**
 * @relayField User.fullName: String
 */
export function fullName(user: UserModel): string {
  return `${user.first} ${user.last}`;
}
```

**Type form**

```ts
/**
 * @relayType User
 */
export function User(id: DataID): UserModel {
  return UserService.getById(id);
}
```

**Pitfalls**
- The function name must match the field name or the type name in the docblock.

### `@rootFragment`

Names the fragment that a derived field reads. The resolver receives a
fragment key and reads it with `readFragment()` from `relay-runtime`.

```ts
/**
 * @relayField User.fullName: String
 * @rootFragment UserFullNameFragment
 */
export function fullName(key: UserFullNameFragment$key): string {
  const user = readFragment(
    graphql`fragment UserFullNameFragment on User { firstName lastName }`,
    key,
  );
  return `${user.firstName} ${user.lastName}`;
}
```

### `@weak`

Marks a model as a value object without an `id`. Used for namespaced field
groups that belong to a parent.

```ts
/**
 * @relayType ProfilePicture
 * @weak
 */
export type ProfilePicture = { url: string; height: number; width: number };
```

### `@live`

Declares a live resolver whose value changes over time. The function must
return a `LiveState<T>`.

```ts
import type { LiveState } from "relay-runtime";
/**
 * @relayField Query.counter: Int
 * @live
 */
export function counter(): LiveState<number> {
  return {
    read: () => store.getState().counter,
    subscribe: (cb) => store.subscribe(cb),
  };
}
```

**Pitfalls**
- Confirm that the value changed before you call the subscriber. Relay
  supports extra notifications, and each one costs work.
- Batch updates with `relayStore.batchLiveStateUpdates` when bursting.

### `@waterfall`

A GraphQL directive on the selection that reads a resolver edge to a server
type. Relay fetches the server data for that edge in a second request, and the
compiler requires `@waterfall` on each read of such a field.

```ts
/**
 * @relayField Post.author: User
 */
export function author(post: PostModel): DataID {
  return post.authorId;
}
```

`User` is a server type that implements `Node`. The resolver returns its ID.

```graphql
fragment PostByline_post on Post {
  author @waterfall {
    name
  }
}
```

---

## Compiler hints

### `@preloadable`

Required when a query is used with `loadQuery` / `useQueryLoader` or from
entrypoints. Causes the compiler to emit a `$Parameters.js` file.

**Where** — query definition.

```graphql
query HomeQuery @preloadable { viewer { ...Feed_viewer } }
```

```tsx
const [queryRef, loadQuery] = useQueryLoader(HomeQuery);
loadQuery({});
```

**Pitfalls**
- Forget `@preloadable` and `loadQuery` will throw at runtime.

### `@raw_response_type`

Emits a type for `optimisticResponse`. Add to any query or mutation whose
optimistic payload you want type-checked.

**Where** — query / mutation definition.

```graphql
mutation ToggleLike($id: ID!) @raw_response_type {
  toggleLike(id: $id) { post { id viewerHasLiked } }
}
```

```tsx
commit({
  variables: { id },
  optimisticResponse: { toggleLike: { post: { id, viewerHasLiked: true } } },
});
```

### `@no_inline`

Prevents the compiler from inlining a fragment into every parent. Useful for
fragments used in many queries, reducing generated artifact size, and required
in some `@module` configurations.

**Where** — fragment definition.

```graphql
fragment Expensive_node on Node @no_inline {
  ... # lots of selections
}
```

**Pitfalls**
- Interacts with `@module` — normal fragments can be auto-`@no_inline` when
  referenced by a module boundary.

### `@match` / `@module`

Data-driven code splitting (3D). `@match` flags a field whose concrete type
determines which bundle to download; `@module` names the bundle per variant.

**Signatures**

```graphql
@match(key: String)              # key optional; compiler derives one
@module(name: "path/to/file.js")
```

**Where** — `@match` on a field returning a union/interface;
`@module` on a fragment spread inside that selection. `@module` also works on
a fragment spread without `@match`.

```graphql
fragment Story_story on Story {
  hero @match {
    ...ImageHero_hero @module(name: "ImageHero.react")
    ...VideoHero_hero @module(name: "VideoHero.react")
  }
}
```

```tsx
import { MatchContainer } from "react-relay";
<MatchContainer match={data.hero} />;
```

**Pitfalls**
- Requires a loader (e.g. Webpack / Haste) that resolves `@module(name:)`
  strings.
- Module-backed fragments should be `@no_inline` (the compiler enforces this).

---

## Cheat sheet

| Directive              | Where                                           | Purpose |
|------------------------|-------------------------------------------------|---------|
| `@argumentDefinitions` | fragment def                                    | Declare fragment args / providers |
| `@arguments`           | fragment spread                                 | Pass values for args |
| `@refetchable`         | fragment on Query / Viewer / Node               | Generate a refetch query |
| `@inline`              | fragment def                                    | Read data outside React render |
| `@relay(plural)`       | fragment def                                    | Fragment expects a list of refs |
| `@relay(mask: false)`  | fragment spread / def                           | Disable data masking |
| `@connection`          | connection field                                | Register a paginated connection |
| `@appendEdge`          | mutation edge field                             | Append edge to connections |
| `@prependEdge`         | mutation edge field                             | Prepend edge to connections |
| `@appendNode`          | mutation node field                             | Wrap node in edge, append |
| `@prependNode`         | mutation node field                             | Wrap node in edge, prepend |
| `@deleteEdge`          | mutation ID/[ID] field                          | Remove edges by node id |
| `@deleteRecord`        | mutation ID field                               | Purge record from store |
| `@defer`               | fragment spread                                 | Stream fragment as follow-up |
| `@stream`              | list field                                      | Stream list items |
| `@stream_connection`   | connection field                                | Stream + connection combined |
| `@required`            | field                                           | Null handling (NONE/LOG/THROW) |
| `@throwOnFieldError`   | query / fragment                                | Throw on field errors; non-null types |
| `@catch`               | field / fragment / query / mutation             | Catch field errors into result |
| `@semanticNonNull`     | schema field definition                         | Mark field non-null except on errors |
| `@alias`               | fragment spread / inline fragment               | Null-safe nested access |
| `@relayField`          | docblock                                        | Define resolver field |
| `@relayType`           | docblock                                        | Define resolver type |
| `@rootFragment`        | docblock                                        | Data a derived resolver reads |
| `@weak`                | docblock                                        | Value-object model without id |
| `@live`                | docblock                                        | Live resolver (LiveState<T>) |
| `@waterfall`           | field reading a resolver edge to a server type  | Acknowledge the second request |
| `@preloadable`         | query def                                       | Emit $Parameters for loadQuery |
| `@raw_response_type`   | query / mutation def                            | Type optimisticResponse |
| `@no_inline`           | fragment def                                    | Don't inline into parents |
| `@match`               | union/interface field                           | 3D code-split selector |
| `@module`              | fragment spread                                 | Bundle path per variant |
