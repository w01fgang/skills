# Updating Data in Relay

Reference for mutating Relay's normalized store: mutations, subscriptions, local updates, connection edits, and imperative store manipulation. Hooks-only.

## Table of Contents

1. [Mental Model](#mental-model)
2. [useMutation](#usemutation)
3. [Auto-Merge by ID vs Updaters](#auto-merge-by-id-vs-updaters)
4. [Optimistic Updates](#optimistic-updates)
5. [Updating Connections](#updating-connections)
6. [Declarative Connection Directives](#declarative-connection-directives)
7. [Imperative Store API](#imperative-store-api)
8. [commitLocalUpdate](#commitlocalupdate)
9. [useSubscription](#usesubscription)
10. [commitPayload](#commitpayload)
11. [Typesafe Updaters](#typesafe-updaters)
12. [Client-Only Data](#client-only-data)
13. [Troubleshooting](#troubleshooting)

---

## Mental Model

Relay stores every fetched record in a normalized cache keyed by `id` (or `__id` for client records). When data changes:

1. **Server response with `id`** — Relay auto-merges into the existing record. No updater needed.
2. **New records, connections, or deletions** — Need either a declarative directive (`@appendEdge`, `@deleteRecord`, ...) or an imperative `updater` function.
3. **Purely local state** — Use `commitLocalUpdate` or updatable fragments/queries.

All subscribed components re-render automatically when records they read change.

---

## useMutation

```tsx
import { useMutation, graphql } from 'react-relay';

const [commit, isInFlight] = useMutation<MyMutation>(graphql`
  mutation MyMutation($input: MyInput!) {
    doThing(input: $input) {
      thing { id name }
    }
  }
`);
```

Returns a tuple: the commit callback and an in-flight boolean. The config object passed to `commit()` accepts:

| Option | Purpose |
|---|---|
| `variables` | Mutation variables (required) |
| `optimisticResponse` | Payload applied immediately, rolled back on error |
| `optimisticUpdater` | Imperative updater run optimistically |
| `updater` | Imperative updater run on server response |
| `onCompleted(response, errors)` | Success callback |
| `onError(error)` | Failure callback |
| `uploadables` | `{ [name]: File }` for multipart file uploads |
| `onNext` | Called for each payload of a multi-payload response |
| `onUnsubscribe` | Called when the returned `Disposable` is disposed |
| `configs` | Legacy declarative configs (`RANGE_ADD`, `RANGE_DELETE`, `NODE_DELETE`). Use the declarative directives. |

### Callback and updater arguments

`commit()` returns a `Disposable`. `dispose()` reverts the optimistic update and suppresses the callbacks. It does not cancel the network request. After the mutation succeeds, `dispose()` does not revert the store.

`isInFlight` is `true` while any mutation committed through the hook is in flight.

| Function | Arguments |
|---|---|
| `updater` | `(store: RecordSourceSelectorProxy, data?: TMutation['response'] \| null)` |
| `optimisticUpdater` | Same signature. `data` is read from `optimisticResponse`, and is `undefined` without one. |
| `onCompleted` | `(response, errors)` |

- `data` holds the fields that the mutation selects directly. Fields that only a spread fragment selects are absent. `data` is read from the response payload only.
- `commitLocalUpdate` updaters take 1 parameter. No network payload exists.
- `onCompleted` receives the mutation selection read from the store after the updaters and the declarative directives run. Fragment spreads stay masked. A record that `@deleteRecord` removed reads as `null`. `errors` is `null` when the response has no errors.
- Relay can run `updater` and `optimisticUpdater` more than once, for example when it rebases optimistic updates. Put side effects in `onCompleted`, which runs once.

```tsx
commit({
  variables,
  updater: (store, data) => {
    const comment = data?.addComment?.comment;
    if (comment == null) return;
    store.get(storyID)?.setValue(true, 'hasNewComment');
  },
});
```

### Basic mutation

```tsx
function RenameButton({ userId, name }: { userId: string; name: string }) {
  const [commit, isInFlight] = useMutation(graphql`
    mutation RenameButtonMutation($input: RenameInput!) {
      renameUser(input: $input) {
        user { id name }
      }
    }
  `);

  return (
    <button
      disabled={isInFlight}
      onClick={() =>
        commit({
          variables: { input: { id: userId, name } },
          onCompleted: () => console.log('saved'),
          onError: err => console.error(err),
        })
      }
    >
      Save
    </button>
  );
}
```

Because `renameUser.user` carries an `id` that is already in the store, Relay merges the new `name` into the existing record and all components reading that user re-render. No updater necessary.

### File uploads

```tsx
commit({
  variables: { input: { avatar: null } },     // placeholder
  uploadables: { 'variables.input.avatar': file },
});
```

The network layer is responsible for turning `uploadables` into a multipart request. See `network.md`.

### cacheConfig

The `useMutation` config type has no `cacheConfig` field. Pass `cacheConfig` to `commitMutation`:

```tsx
commitMutation(environment, {
  mutation,
  variables,
  cacheConfig: { force: true, metadata: { trace: true } },
});
```

---

## Auto-Merge by ID vs Updaters

Relay auto-handles these with no updater:

- **Field on an existing record** — response contains the record's `id` and the changed fields.
- **Entire existing record replaced** — same as above; merged by `id`.

You **need an updater or directive** when:

- Inserting/removing items in a `@connection`.
- Creating a brand-new record that should appear in a list but the field selection alone wouldn't put it there.
- Deleting a record (`@deleteRecord` or imperative `store.delete(id)`).
- Referencing the new record from some existing root that Relay doesn't see in the response.

### Auto-merge (no updater needed)

```graphql
mutation LikeMutation($input: LikeInput!) {
  likePost(input: $input) {
    post {
      id
      likeCount
      viewerDoesLike
    }
  }
}
```

### Needs a directive — adding a comment to a connection

```graphql
mutation AddCommentMutation($input: AddCommentInput!, $connections: [ID!]!) {
  addComment(input: $input) {
    commentEdge @appendEdge(connections: $connections) {
      cursor
      node { id body }
    }
  }
}
```

### Fragment-spread pattern

Spread the same fragments your UI reads so the response includes every field the components need:

```graphql
mutation UpdatePostMutation($input: UpdatePostInput!) {
  updatePost(input: $input) {
    post {
      ...PostCard_post
      ...PostDetail_post
    }
  }
}
```

---

## Optimistic Updates

Relay applies optimistic data before the network resolves and rolls it back automatically on success (the real response replaces it) or on error.

### optimisticResponse

A fake server payload. Requires `@raw_response_type` on the mutation to type it.

```tsx
const [commit] = useMutation(graphql`
  mutation ToggleLikeMutation($input: LikeInput!) @raw_response_type {
    likePost(input: $input) {
      post { id likeCount viewerDoesLike }
    }
  }
`);

commit({
  variables: { input: { id: post.id } },
  optimisticResponse: {
    likePost: {
      post: {
        id: post.id,
        likeCount: post.likeCount + (post.viewerDoesLike ? -1 : 1),
        viewerDoesLike: !post.viewerDoesLike,
      },
    },
  },
});
```

### optimisticUpdater

Use when the optimistic change cannot be expressed as a static response — e.g. inserting into a connection, or modifying unrelated records.

```tsx
commit({
  variables,
  optimisticUpdater: store => {
    const post = store.get(postId);
    if (!post) return;
    post.setValue((post.getValue('likeCount') as number) + 1, 'likeCount');
    post.setValue(true, 'viewerDoesLike');
  },
  updater: store => {
    // runs after server response — usually the same logic
  },
});
```

### Execution order

1. Apply `optimisticResponse`.
2. Run `optimisticUpdater`.
3. Apply optimistic declarative directives (`@appendEdge`, ...).
4. Server resolves.
5. Roll back all optimistic changes.
6. Apply real response, apply real directives, run `updater`.
7. Fire `onCompleted` (or `onError` + skip step 6 on failure).

Stacking multiple in-flight optimistic responses on the same fields can cause UI flicker; prefer a single source of truth per record.

Rollback rules:

- Relay reverts every optimistic change of a mutation when the response or the error arrives.
- If another write changes the store while the mutation is in flight, Relay reverts the optimistic update, applies the write, and re-applies the optimistic update.
- Relay does not recalculate a second optimistic value after the first one rolls back. With 2 optimistic responses that each add 1 to a like count, the first rollback leaves the count at +2. Use `optimisticUpdater` to compute the value from the store.
- In the v21 source (`RelayPublishQueue._publishSourceFromPayload`), the handlers behind the declarative directives (`@appendEdge`, `@deleteEdge`, ...) run before the real `updater`. Do not rely on `updater` seeing the store before the directives apply.

---

## Updating Connections

A `@connection` is stored as a record containing `edges`, `pageInfo`, and metadata. To modify it you need its **connection ID** — derived from the parent record ID plus the connection key (and any identity-forming filter arguments).

### Three ways to get the connection record

**1. `__id` from the fragment** — simplest when you already render the list:

```tsx
const data = useFragment(graphql`
  fragment CommentList_story on Story {
    comments(first: 20) @connection(key: "CommentList_story_comments") {
      __id
      edges { node { id body } }
    }
  }
`, storyRef);

const connectionID = data.comments.__id;
```

`store.get(connectionID)` returns the connection record inside an updater:

```ts
function updater(store: RecordSourceSelectorProxy) {
  const connection = store.get(connectionID);
}
```

**2. `ConnectionHandler.getConnectionID(parentID, key, filters?)`**:

```tsx
import { ConnectionHandler } from 'relay-runtime';

const connectionID = ConnectionHandler.getConnectionID(
  storyID,
  'CommentList_story_comments',
  { orderBy: 'DATE' },
);
```

**3. `ConnectionHandler.getConnection(parentRecord, key, filters?)`** — inside an updater:

```ts
function updater(store: RecordSourceSelectorProxy) {
  const story = store.get(storyID);
  const connection = ConnectionHandler.getConnection(
    story!,
    'CommentList_story_comments',
  );
}
```

### Connection identity and filters

Filter arguments (excluding pagination args `first/last/before/after`) are part of the connection identity. Two connections with different `orderBy` are two different records. Control which args count via the `filters` array:

```graphql
fragment CommentList_story on Story {
  comments(orderBy: $orderBy, lang: $lang)
    @connection(key: "CommentList_story_comments", filters: ["orderBy"]) {
    edges { node { id } }
  }
}
```

Here `lang` is excluded from identity: swapping languages reuses the same connection.

### ConnectionHandler — imperative edits

```ts
import { ConnectionHandler } from 'relay-runtime';

function updater(store: RecordSourceSelectorProxy) {
  const connection = ConnectionHandler.getConnection(
    store.get(storyID)!,
    'CommentList_story_comments',
  );
  if (!connection) return;

  // Insert a server-returned edge
  const payload = store.getRootField('addComment');
  const newEdge = payload!.getLinkedRecord('commentEdge');
  ConnectionHandler.insertEdgeAfter(connection, newEdge!);

  // Or build an edge from scratch
  const newComment = store.create(`client:comment:${Date.now()}`, 'Comment');
  newComment.setValue('hello', 'body');
  const edge = ConnectionHandler.createEdge(store, connection, newComment, 'CommentEdge');
  ConnectionHandler.insertEdgeBefore(connection, edge);

  // Remove a node by id
  ConnectionHandler.deleteNode(connection, oldCommentID);
}
```

API summary:

| Method | Returns | Purpose |
|---|---|---|
| `getConnection(record, key, filters?)` | `RecordProxy \| null` | Look up connection record |
| `getConnectionID(parentID, key, filters?)` | `string` | Compute the connection's data-ID |
| `createEdge(store, connection, node, edgeType)` | `RecordProxy` | Build a new edge wrapping a node (for locally-created nodes) |
| `buildConnectionEdge(store, connection, edge)` | `RecordProxy \| null` | Reconstruct an edge from a server response payload before inserting |
| `insertEdgeAfter(connection, edge, cursor?)` | void | Append to edges |
| `insertEdgeBefore(connection, edge, cursor?)` | void | Prepend to edges |
| `deleteNode(connection, nodeID)` | void | Remove edges whose `node.id` matches |

---

## Declarative Connection Directives

Prefer these over imperative updaters. They rollback with the mutation automatically.

Pass connection IDs as a mutation variable `$connections: [ID!]!`.

```tsx
const connectionID = data.comments.__id;

commit({
  variables: {
    input: { storyID, body },
    connections: [connectionID],
  },
});
```

### @appendEdge / @prependEdge

Server returns a full edge; Relay inserts it.

```graphql
mutation AddCommentMutation($input: AddCommentInput!, $connections: [ID!]!) {
  addComment(input: $input) {
    commentEdge @appendEdge(connections: $connections) {
      cursor
      node { id body author { name } }
    }
  }
}
```

### @appendNode / @prependNode

Server returns the node; Relay synthesizes an edge with the given `edgeTypeName`.

```graphql
mutation AddCommentMutation($input: AddCommentInput!, $connections: [ID!]!) {
  addComment(input: $input) {
    comment @appendNode(connections: $connections, edgeTypeName: "CommentEdge") {
      id
      body
    }
  }
}
```

### @deleteEdge

Field must be `ID` or `[ID!]!` — removes every edge whose `node.id` matches.

```graphql
mutation RemoveCommentsMutation($input: RemoveCommentsInput!, $connections: [ID!]!) {
  removeComments(input: $input) {
    deletedIDs @deleteEdge(connections: $connections)
  }
}
```

### @deleteRecord

Applied to a scalar `ID` field; deletes that record from the store. An edge that still points to the deleted record reads `undefined`. Add `@deleteEdge` to remove the edge from a connection.

```graphql
mutation DeletePostMutation($input: DeletePostInput!) {
  deletePost(input: $input) {
    deletedPostID @deleteRecord
  }
}
```

### Directive behavior

- `@appendEdge`, `@prependEdge`, `@appendNode` and `@prependNode` do not insert a node that the connection already contains. The connection does not change and subscribers receive no notification (v21 test `RelayModernEnvironment-ExecuteMutationWithDeclarativeMutation-test.js`; the same test exists on v20).
- `@appendNode` and `@prependNode` log the warning `MutationHandlers: Expected target node to exist.` when the server returns `null` for the node.
- The directives also work on query fields.
- Relay applies the directives to the `optimisticResponse` first, then to the server response. On error, it rolls back both.

### Before / after

**Before** (imperative):

```ts
updater: store => {
  const conn = ConnectionHandler.getConnection(store.get(storyID)!, KEY)!;
  const payload = store.getRootField('addComment')!;
  const edge = payload.getLinkedRecord('commentEdge')!;
  ConnectionHandler.insertEdgeAfter(conn, edge);
}
```

**After** (declarative):

```graphql
addComment(input: $input) {
  commentEdge @appendEdge(connections: $connections) {
    cursor
    node { id }
  }
}
```

---

## Imperative Store API

Updater functions receive a store proxy. Three proxy types:

- **`RecordSourceSelectorProxy`** — passed to mutation `updater`/`optimisticUpdater` and `useSubscription` updaters. Has `getRootField`, `getPluralRootField` in addition to source methods.
- **`RecordSourceProxy`** — passed to `commitLocalUpdate`. No root-field helpers.
- **`RecordProxy`** — an individual record.

### RecordSourceProxy / RecordSourceSelectorProxy

| Method | Description |
|---|---|
| `get(dataID)` | `RecordProxy \| null \| undefined` for the given id |
| `getRoot()` | The `Query` root record |
| `create(dataID, typeName)` | Create a new record |
| `delete(dataID)` | Evict a record from the store |
| `invalidateStore()` | Mark entire store as stale — next query refetches |
| `getRootField(fieldName)` *(selector only)* | Read a field off the mutation/subscription response root |
| `getPluralRootField(fieldName)` *(selector only)* | Same for list-valued root fields |

### RecordProxy

| Method | Description |
|---|---|
| `getDataID()` | Record's ID |
| `getType()` | GraphQL type name |
| `getValue(name, args?)` | Read a scalar field |
| `setValue(value, name, args?)` | Write a scalar field |
| `getLinkedRecord(name, args?)` | Traverse to a single linked record |
| `setLinkedRecord(record, name, args?)` | Replace a singular link |
| `getOrCreateLinkedRecord(name, typeName, args?)` | Create the link if missing |
| `getLinkedRecords(name, args?)` | Plural version |
| `setLinkedRecords(records, name, args?)` | Plural version |
| `copyFieldsFrom(otherRecord)` | Shallow-copy all fields |
| `invalidateRecord()` | Mark record stale so next query refetches |

### Example — imperative updater

```ts
import type { RecordSourceSelectorProxy } from 'relay-runtime';

function updater(store: RecordSourceSelectorProxy) {
  const payload = store.getRootField('createTodo');       // RecordProxy
  const newTodo = payload?.getLinkedRecord('todo');
  if (!newTodo) return;

  const user = store.get(viewerID);
  const todos = user?.getLinkedRecords('todos') ?? [];
  user?.setLinkedRecords([...todos, newTodo], 'todos');

  // scalar tweak
  const count = (user?.getValue('todoCount') as number) ?? 0;
  user?.setValue(count + 1, 'todoCount');
}
```

### Arguments on fields

Fields parameterised with arguments must be read/written with the same args:

```ts
record.getValue('title', { locale: 'en' });
record.setValue('Hi', 'title', { locale: 'en' });
```

---

## commitLocalUpdate

Pure client-side store edits — no network. The updater receives a `RecordSourceProxy`.

```tsx
import { commitLocalUpdate, graphql } from 'react-relay';
import { useRelayEnvironment } from 'react-relay';

function ClearDrafts() {
  const env = useRelayEnvironment();
  return (
    <button
      onClick={() =>
        commitLocalUpdate(env, store => {
          const viewer = store.getRoot().getLinkedRecord('viewer');
          viewer?.setLinkedRecords([], 'drafts');
        })
      }
    >
      Clear drafts
    </button>
  );
}
```

Common uses: seeding client-only fields, toggling local UI state stored in Relay, clearing/resetting records, priming data before a mutation.

### Creating a client-only record

```ts
commitLocalUpdate(env, store => {
  const id = `client:Draft:${Date.now()}`;
  const draft = store.create(id, 'Draft');
  draft.setValue('', 'body');
  draft.setValue(Date.now(), 'createdAt');

  const viewer = store.getRoot().getLinkedRecord('viewer')!;
  const drafts = viewer.getLinkedRecords('drafts') ?? [];
  viewer.setLinkedRecords([...drafts, draft], 'drafts');
});
```

All subscribed components re-render.

---

## useSubscription

Live server-pushed updates. Same auto-merge rules as mutations; supply an `updater` for list/deletion work.

```tsx
import { useSubscription, graphql } from 'react-relay';
import { useMemo } from 'react';
import type { GraphQLSubscriptionConfig } from 'relay-runtime';

function CommentsTail({ storyID, connectionID }: { storyID: string; connectionID: string }) {
  const config = useMemo<GraphQLSubscriptionConfig<CommentAddedSubscription>>(() => ({
    subscription: graphql`
      subscription CommentAddedSubscription($storyID: ID!, $connections: [ID!]!) {
        commentAdded(storyID: $storyID) {
          commentEdge @appendEdge(connections: $connections) {
            cursor
            node { id body }
          }
        }
      }
    `,
    variables: { storyID, connections: [connectionID] },
    onError: err => console.error(err),
    onCompleted: () => console.log('unsubscribed'),
  }), [storyID, connectionID]);

  useSubscription(config);
  return null;
}
```

Config options: `subscription`, `variables`, `updater`, `onNext`, `onError`, `onCompleted`, `cacheConfig`.

Use an `updater` for cases directives can't express:

```tsx
useSubscription({
  subscription,
  variables,
  updater: store => {
    const event = store.getRootField('commentAdded');
    // ...imperative edits
  },
});
```

---

## commitPayload

Writes a synthetic query response into the store — useful for seeding from non-GraphQL sources.

```ts
import { createOperationDescriptor, getRequest } from 'relay-runtime';
import type { FooQueryRawResponse } from './__generated__/FooQuery.graphql';
import FooQuery from './__generated__/FooQuery.graphql';

const op = createOperationDescriptor(getRequest(FooQuery), { id: '1' });
const payload: FooQueryRawResponse = { node: { __typename: 'User', id: '1', name: 'Ada' } };
environment.commitPayload(op, payload);
```

The payload is processed like a query response, and it resolves data-driven dependencies. Relay processes each `@defer` fragment at once from the payload data, because a client payload has no later incremental payload. Relay does not process `@stream` placeholders of a client payload. Use `@raw_response_type` on the query to generate the payload type.

---

## Typesafe Updaters

Typesafe updaters replace `setValue` and `setLinkedRecord` calls with typed property assignment. The API is identical on v20 and v21.

| Directive | Where | Purpose |
|---|---|---|
| `@updatable` | query, fragment definition | Selects the fields that an updater reads and writes. Relay never fetches them. |
| `@assignable` | fragment definition | Marks a type that a linked field accepts. The fragment contains only `__typename`. |

`readUpdatableFragment(fragment, ref)` and `readUpdatableQuery(query, variables)` exist on `RecordSourceProxy` and `RecordSourceSelectorProxy`. Both return `{ updatableData }`. Assigning to a property of `updatableData` writes to the store.

### Scalar fields

```tsx
commit({
  variables,
  updater: (store, response) => {
    const feedbackRef = response?.feedback_create?.feedback;
    if (feedbackRef == null) return;
    const { updatableData } = store.readUpdatableFragment(
      graphql`
        fragment CreateFeedback_updatable_feedback on Feedback @updatable {
          is_new_comment
        }
      `,
      feedbackRef,
    );
    updatableData.is_new_comment = true;
  },
  // The mutation selects ...CreateFeedback_updatable_feedback under feedback.
});
```

`readUpdatableQuery` needs no fragment reference. It suits click handlers that call `commitLocalUpdate`:

```tsx
commitLocalUpdate(environment, store => {
  const { updatableData } = store.readUpdatableQuery(
    graphql`query NameUpdaterUpdateQuery @updatable { viewer { name } }`,
    {},
  );
  if (updatableData.viewer != null) updatableData.viewer.name = newName;
});
```

Use `readUpdatableQuery` when you have no fragment reference, when the parent is the `Query` root (an updatable fragment cannot be spread at the top level), or when the selection needs variables. An updatable fragment reuses the variables of the query that spreads it.

### Rules

- Relay never fetches the fields of an updatable query or fragment, even when a regular query spreads the fragment. To fetch and update a field, select it in a regular selection as well.
- Updatable data can be missing when the store does not hold the record.
- An updatable selection cannot spread regular fragments. `@defer` and similar directives are not allowed.
- `id`, `__id`, `__typename` and `js` have no setter.
- `readUpdatableFragment` does not accept plural fragment references (v21 source `readUpdatableFragment.js`).

### Linked fields

An assignment to a linked field needs the same `@assignable` fragment on the source and on the destination field:

```tsx
graphql`
  fragment AssignBestFriendButton_assignable_user on User @assignable {
    __typename
  }
`;

// source: a read-only fragment
const data = useFragment(graphql`
  fragment AssignBestFriendButton_someType on SomeType {
    user { name ...AssignBestFriendButton_assignable_user }
  }
`, someTypeRef);

commitLocalUpdate(environment, store => {
  const { updatableData } = store.readUpdatableQuery(
    graphql`
      query AssignBestFriendButtonUpdatableQuery @updatable {
        viewer { best_friend { ...AssignBestFriendButton_assignable_user } }
      }
    `,
    {},
  );
  if (data.user != null && updatableData.viewer != null) {
    updatableData.viewer.best_friend = data.user;
  }
});
```

- Every assigned value originates in a read-only fragment, query, mutation or subscription. `updatableData.foo = updatableData.foo` is invalid.
- To append to a list, select the current list in a read-only fragment (with the `@assignable` spread on its items) and assign a new array: `updatableData.viewer.best_friends = [...viewer.best_friends, data.user]`.
- Assigning `null` to a singular linked field sets the link to `null`. Check for `null` first.
- Assigning `null` to a plural linked field throws. Assign `[]` instead. Items must not be `null`.
- The assigned record must exist in the store. Otherwise Relay throws `Did not find item with data id <id> in the store.`
- The assigned object guarantees only `__typename`. A consumer cannot assume that other fields are present.
- To assign from an abstract type, refine it with an inline fragment and check `__typename`:

```tsx
const data = useFragment(graphql`
  fragment Foo_query on Query {
    node(id: "4") {
      ... on User { __typename ...AssignBestFriendButton_assignable_user }
    }
  }
`, queryRef);

if (data.node != null && data.node.__typename === 'User' && updatableData.viewer != null) {
  updatableData.viewer.best_friend = data.node;
}
```

- Assignment to an interface-typed field (for example `Actor`) from a source that implements the interface needs no extra step. When the source type is not known to implement the interface (for example `Node`), the compiler emits `__isFoo_actor?: string`, and the assignment fails to type-check. Each generated artifact exports a `validate` function that returns the value (with the non-optional type) or `false`. The docs show this function in Flow-commented JavaScript. The TypeScript artifact has the same function with TypeScript type annotations (`relay-typegen/src/write.rs`).

```tsx
import { validate as validateActor } from './__generated__/Foo_actor.graphql';

const validActor = validateActor(data.node);
if (validActor !== false) updatableData.viewer.actor = validActor;
```

Sources: `guided-tour/updating-data/imperatively-modifying-store-data`, `imperatively-modifying-linked-fields`, `typesafe-updaters-faq` (v21 docs); `packages/relay-runtime/mutations/createUpdatableProxy.js` (v21 tag).

---

## Client-Only Data

Client schema extensions add fields and types that the server does not define. List the `.graphql` files or folders in the `schemaExtensions` compiler option (see `network.md` section 12 for the config).

- A new client field reads as `undefined` until an updater writes it. Prime it with `commitLocalUpdate`:

```ts
commitLocalUpdate(environment, store => {
  const user = store.getRoot().getLinkedRecord('viewer');
  user?.setLinkedRecords([], 'notes');
});
```

- A query that mixes client and server fields with `useLazyLoadQuery` needs at least 1 server field. An introspection field such as `__typename` counts. A query with only client fields uses `useClientQuery`.
- Create client records with an ID that starts with `client:`, such as `client:Note:1`.
- A mounted query retains its data. For data that no component renders, call `environment.retain(operation)` and dispose the result when the data can be garbage collected.
- To delete a client record, remove it from the parent list with `setLinkedRecords` and call `store.delete(id)`. Edges to a deleted record read as `undefined`, even when the type is non-null. With `@throwOnFieldError`, the read throws.
- Mutation and subscription updaters can also write client fields, because the response never contains them.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| UI doesn't update after mutation | Response missing the `id` field on changed records | Add `id` to every changed selection; Relay merges by id |
| New item not showing in list | List is a `@connection` and mutation didn't touch it | Add `@appendEdge`/`@appendNode` or write an `updater` |
| Declarative directive did nothing | `connections` variable empty or wrong connection ID | Read `data.yourConnection.__id` and pass in `[ID!]!` variable |
| "Cannot read property '__id' of null" | Fragment ref resolved to null before connection loaded | Guard on the parent or pass connection ID from a loaded-state branch |
| Optimistic update flickers then reverts on success | Server response differs from optimistic shape, missing fields | Spread the same fragments in mutation response; supply all fields the UI reads |
| Connection updates wrong list after filter change | Filter arg included in connection identity | Add arg to `@connection(filters: [...])` only for args that truly distinguish results |
| `ConnectionHandler.getConnection` returns null | Wrong key, wrong parent record, or missing filter args | Match `key` exactly and pass the same filters used in the fragment |
| Deleted record still in list | `@deleteRecord` only evicts; if the list is not a `@connection`, references are not cleaned | Use `@deleteEdge` on a connection, or write an updater that removes from `setLinkedRecords` |
| File upload ignored | Network layer not multipart-aware | Implement multipart in your `fetchFn`; path in `uploadables` key must match variable path |
| `optimisticResponse` type error | Missing `@raw_response_type` on the mutation | Add the directive; regenerate types |
| Two optimistic responses stomping each other | Overlapping optimistic writes on same fields | Collapse into one optimistic updater or serialize the mutations |
| Record stale after external change | Store thinks data fresh | Call `record.invalidateRecord()` or `store.invalidateStore()` |
| `commitLocalUpdate` change not re-rendering | Component reads a different record than the one edited | Verify you edited the exact `dataID` being rendered; check with `getDataID()` |
| Subscription updates duplicate edges | Server emits edges already in the connection | Guard in updater: `ConnectionHandler.deleteNode` first, or dedupe by id |
| "Missing field 'X' on record" warning | Wrote partial data via `create` without required selected fields | Set every field the UI reads, or refetch via `invalidateRecord` |
| Client-only field reads `undefined` | No updater wrote the field yet | Prime it with `commitLocalUpdate` |
| Query with only client fields misbehaves under `useLazyLoadQuery` | The docs require at least 1 server field per such query | Add a server field such as `__typename`, or use `useClientQuery` |
| `Did not find item with data id <id> in the store.` | Typesafe assignment of a record that the store does not hold | Fetch or create the record before the assignment |
| Assigning `null` to a plural linked field throws | Plural setters reject `null` | Assign `[]` |
| Updatable field is `undefined` after `readUpdatableFragment` | Relay never fetches updatable fields | Select the field in a regular query or fragment too |
| Like count stays +2 after one optimistic rollback | Relay does not recalculate later optimistic values | Compute the value in `optimisticUpdater` from the store |
| `updater` argument `data` is `null` | Mutation returned no data | Guard with `data?.field` |
