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
- `get()` returns the same value on every call within a run. A parent cannot pass a provided variable through `@arguments`. Relay renames provided variables to `__relay_internal__pv__<Module>` in the operation (unstable; visible when you debug a query).
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
- A spread of an `@inline` fragment accepts `@alias` and `@dangerously_unaliased_fixme` only. Each other directive on the spread (`@defer`, `@module`, `@include`, `@skip`) is a compiler error.
- Not a substitute for `useFragment` — component render must still subscribe.

### `@relay(plural: Boolean)`

Marks a fragment as expecting an array of refs. The fragment spread sits inside
a list field.

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
  prefetchable_pagination: Boolean = false  # required by usePrefetchableForwardPaginationFragment
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

These directives operate on **mutation, subscription or query response fields** and need a
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

Deletes the record from the Relay store. An edge that still points to the
record reads `undefined`.

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
- `@deleteRecord` deletes the record for every reader. Use `@deleteEdge` to
  remove an edge from specific connections.

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
- `@defer` on a spread of an `@inline` fragment is a compiler error.

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

### `@defer` / `@stream` arguments

The exported v20 and v21 sources do not define `@defer` and `@stream`. The
argument names below come from the runtime tests and `RelayResponseNormalizer.js`,
identical on v20 and v21 (`initial_count` appears 55 times in each; `initialCount`
appears 0 times).

| Argument | Applies to | Rule |
|----------|-----------|------|
| `label` | `@defer`, `@stream` | String that identifies the incremental chunk |
| `if` | `@defer`, `@stream` | Boolean literal or variable. Any other value logs a dev warning. |
| `initial_count` | `@stream` | Snake case. Number of items in the initial payload. |

- `@defer(if: false)`: the data arrives in the initial payload. Relay expects no extra chunk.
- `@stream(if: false)`: Relay normalizes the initial array and registers no streaming placeholder.
- `@stream` always normalizes the items of the initial payload, including the first `initial_count` items.

### `@stream_connection`

`@connection` plus streaming. Used with `usePaginationFragment`; items past
`initial_count` arrive in follow-up payloads.

**Signature** — accepts every `@connection` argument plus
`label: String`, `initial_count: Int!`, `if: Boolean = true` and `use_customized_batch: Boolean = false`.

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
- The v21 and v20 SDL (`relay-extensions.graphql`) declares `@stream_connection(key: String!, filters: [String], handler: String, label: String, initial_count: Int!, if: Boolean = true, use_customized_batch: Boolean = false, dynamicKey_UNSTABLE: String, prefetchable_pagination: Boolean = false)`. The SDL marks `initial_count` as required (`Int!`). The Streaming Pagination guide calls it optional with default 0. Pass it always.

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
| `DANGEROUSLY_THROW_ON_SEMANTICALLY_NULLABLE_FIELD` | v21 only. Same as `THROW`, allowed on nullable fields when the `disallow_required_action_throw_on_semantically_nullable_fields` feature flag is on. A migration aid; avoid new uses. |

**Pitfalls**
- `@required` applies to the reader, not the network — the field is still
  fetched.
- If every selection on a parent object is `@required(THROW)`, the parent is
  effectively non-null when reading.
- A `@required` field cannot have an `action` less severe than its `@required`
  parent (`NONE` < `LOG` < `THROW`).
- Inside a `@connection`, `@required` on the `node` field or on its direct
  child fields is a compiler error.
- `@required` is local to the fragment. Every selection of the same field in 1
  fragment (for example in several inline fragments) must carry the same
  `@required` declaration. Otherwise the compiler reports
  `All references to a field must have matching @required declarations.`
- `@required` on a top-level field of a fragment can make the object that
  `useFragment` returns nullable.
- In a plural field, a missing `@required(action: LOG)` field sets the list item
  to `null`. The list stays an array.
- A `@required` field inside an inline fragment stays optional in the types,
  because the object can have another type. Select `__typename` next to the
  inline fragment to get a discriminated union.
- `@required` on a fragment spread that has `@alias` is not supported.
- Under a `@catch` ancestor, a null `@required(action: THROW)` field bubbles up
  as a caught error. The read does not throw.

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
- An error bubbles to the nearest `@catch` ancestor. With `@catch` on `viewer`,
  an error on `viewer.name` yields `viewer: { ok: false, errors: [{ path: ['viewer', 'name'] }] }`.
  With `@catch` on `name`, the error stays on `name`.
- `@catch` also catches a null `@required(action: THROW)` field below it and
  missing data (store data absent for a selected field).
- Fields that `@catch` covers use their semantic nullability in the generated
  types. A `@semanticNonNull` field is non-null there.
- `@catch` without `@throwOnFieldError` still returns the error in the data.
  Fields outside any `@catch` do not throw.

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

Schema declaration (SDL):

```graphql
directive @semanticNonNull(levels: [Int] = [0]) on FIELD_DEFINITION
```

Relay reads the directive from the schema file. Add a React error boundary above
each component that reads a `@throwOnFieldError` fragment. The extension SDL
comment names a typegen option
`experimental_emit_semantic_nullability_types`. No compiler source file at tag
v20.1.1 or v21.0.1 reads that name. Use `@throwOnFieldError` or `@catch` to get
the non-null types.

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

**Conditional spreads.** `@alias` on a spread with `@skip` / `@include` or an
abstract type condition exposes the fragment key as a nullable field. A null
check shows whether Relay fetched the fragment:

```graphql
fragment MyFragment on User {
  ...ConditionalData @skip(if: $someVar) @alias
}
```

```tsx
if (user.ConditionalData == null) return "No data fetched";
return <ConditionalData userKey={user.ConditionalData} />;
```

**Grouping required fields.** An aliased inline fragment without a type
condition groups fields that use `@required(action: NONE)`. One null check covers
the group:

```graphql
fragment MyFragment on User {
  id
  ... @alias(as: "requiredFields") {
    name @required(action: NONE)
    email @required(action: NONE)
  }
}
```

If `name` or `email` is null, `user.requiredFields` is null and `id` stays set.

**Enforcement.** Relay requires `@alias` on every conditionally fetched spread
(`@skip` / `@include`, or a type condition that can mismatch). The compiler
feature flag `enforce_fragment_alias_where_ambiguous` controls the check. The
alias guide says to disable the flag to turn the validation off. The directive
`@dangerously_unaliased_fixme` (on `FRAGMENT_SPREAD`) suppresses the error on an
existing spread. Do not add new uses. Replace each use with `@alias`. The
`mark-dangerous-conditional-fragment-spreads` codemod (see `codemods.md`)
applies the directive project-wide. The Relay VS Code extension offers quick
fixes for both.

---

## Resolvers

Resolver tags live in **docblock comments** on exported TS/JS functions and
types in files the Relay compiler scans. **The tag depends on the Relay
version:** v21 reads `@relayType` and `@relayField`; v20 reads the single tag
`@RelayResolver` for both. The examples below use the v21 tags. On v20, write
`@RelayResolver` in their place. `relay-compiler codemod fix-all` (v21 only)
migrates the tags.

### `@relayField` and `@relayType` (v20: `@RelayResolver`)

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
 * @relayField Post.author: ServerUser
 */
export function author(post: PostModel): DataID {
  return post.authorId;
}
```

`ServerUser` is a server type that implements `Node`. The resolver returns its ID.

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
- With the `no_inline` feature flag on, `@module` makes its fragment `@no_inline` implicitly. If a regular spread also uses that fragment, the compiler requires an explicit `@no_inline` on the fragment definition.

**Rules (Server 3D and Client 3D)**

- Wrap `MatchContainer` in `Suspense`. It can suspend while it loads the component or its data.
- The loaded component reads the data on a prop named like the fragment suffix. For `Comment_comment`, the prop is `comment`, not `comment$key`.
- 2 `@module` spreads under 1 `@match` field must target different concrete types. They can share an abstract parent (union or interface).
- A fragment with 2 or more 3D fields needs a distinct key on each field after the first. The compiler reports `Invalid @module selection: documents with multiple fields containing 3D selections must specify a unique 'key' value for each field`. Add the key:

```graphql
fragment Example_comment on Comment {
  comment_content_renderer @match {
    ...CommentMarkdownRenderer_comment @module(name: "CommentMarkdownRenderer.react")
  }
  attachments {
    attachment_renderer @match(key: "Example_comment__attachment") {
      ...CommentAttachmentPhotoRenderer_comment @module(name: "CommentPhotoRenderer.react")
    }
  }
}
```

- `@module` also works without `@match` on a single concrete type, as in `image { ...CommentImage_image @module(name: "CommentImage.react") }`.

**Server 3D** needs server support. In OSS, each concrete type exposes `__component: JSDependency` and `__fragment: JSDependency`, and the `@match` field takes a `supported: [String!]` argument that the compiler fills in. The docs say Relay does not fully support Server 3D in OSS.

**Client 3D** reads data from client-side resolvers (interface in a client schema extension, concrete resolver types that implement it, query through `useClientQuery`). It needs the `moduleImportConfig` compiler option:

```json
{
  "moduleImportConfig": {
    "dynamicModuleProvider": { "mode": "Custom", "statement": "() => require('./<$module>')" },
    "surface": "resolvers"
  }
}
```

`<$module>` stands for the `@module(name:)` value. In OSS, `mode` is `Custom` and `surface` is `resolvers`. Client 3D can need extra round trips, because the client renders first to learn which code to load. Avoid nested Client 3D.

---

## Typesafe updaters

### `@updatable` / `@assignable`

`@updatable` (query or fragment definition) marks a selection that
`store.readUpdatableQuery` / `store.readUpdatableFragment` read and write. Relay
never fetches its fields. `@assignable` (fragment definition) marks a type that
a linked field accepts. Its only field is `__typename`. Both exist on v20 and
v21 with the same definition. See `updating-data.md`, "Typesafe Updaters".

```graphql
fragment Foo_updatable_user on User @updatable { is_selected }
fragment Foo_assignable_user on User @assignable { __typename }
```

## Compiler config tied to directives

| Option | Directive | Effect |
|--------|-----------|--------|
| `schemaExtensions` | client schema | Array of files or folders with client `.graphql` schema extensions |
| `moduleImportConfig` | `@module` | `dynamicModuleProvider` (`mode`, `statement`) and `surface` for Client 3D |
| `featureFlags.enforce_fragment_alias_where_ambiguous` | `@alias` | Requires `@alias` on conditional spreads. Default `enabled` in v21.0.1. In v20.1.1 the default applies when the config has a `featureFlags` object; set the flag explicitly on v20. |
| `featureFlags.disallow_required_action_throw_on_semantically_nullable_fields` | `@required` | Rejects `THROW` on nullable fields that lack `@semanticNonNull`. Default `disabled`. v21 only. |
| `featureFlags.allow_legacy_relay_resolver_tag` | resolver docblocks | Accepts `@RelayResolver` as an alias of `@relayType` / `@relayField`. Default `disabled`. v21 only. |

Source: `relay-compiler-config-schema.json` (main branch). The v20 and v21
tags do not export the config source. A flag value is `{ "kind": "enabled" }`,
`{ "kind": "disabled" }` or a rollout (`{ "kind": "rollout", "rollout": 20 }`).

## Directive definitions that differ between v20 and v21

Only 2 definitions differ in `relay-extensions.graphql`:

- `RequiredFieldAction` gains `DANGEROUSLY_THROW_ON_SEMANTICALLY_NULLABLE_FIELD` in v21.
- `@exec_time_resolvers` gains the argument `useExperimentalProvider: String` in v21.

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
| `@dangerously_unaliased_fixme` | fragment spread                         | Suppress the `@alias` enforcement error; do not add new uses |
| `@updatable`           | query / fragment def                            | Typesafe updater selection; never fetched |
| `@assignable`          | fragment def                                    | Type accepted by a linked-field assignment |
| `@relayField`          | docblock                                        | Define resolver field (v20: `@RelayResolver`) |
| `@relayType`           | docblock                                        | Define resolver type (v20: `@RelayResolver`) |
| `@rootFragment`        | docblock                                        | Data a derived resolver reads |
| `@weak`                | docblock                                        | Value-object model without id |
| `@live`                | docblock                                        | Live resolver (LiveState<T>) |
| `@waterfall`           | field reading a resolver edge to a server type  | Acknowledge the second request |
| `@preloadable`         | query def                                       | Emit $Parameters for loadQuery |
| `@raw_response_type`   | query / mutation def                            | Type optimisticResponse |
| `@no_inline`           | fragment def                                    | Don't inline into parents |
| `@match`               | union/interface field                           | 3D code-split selector |
| `@module`              | fragment spread                                 | Bundle path per variant |
