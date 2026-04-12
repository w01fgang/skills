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
11. [Troubleshooting](#troubleshooting)

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

```tsx
commit({
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
6. Apply real response, run `updater`, apply real directives.
7. Fire `onCompleted` (or `onError` + skip step 6 on failure).

Stacking multiple in-flight optimistic responses on the same fields can cause UI flicker; prefer a single source of truth per record.

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

Applied to a scalar `ID` field; evicts that record from the store entirely (and therefore from every connection referencing it).

```graphql
mutation DeletePostMutation($input: DeletePostInput!) {
  deletePost(input: $input) {
    deletedPostID @deleteRecord
  }
}
```

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

Pure client-side store edits — no network. The updater receives a `RecordSourceSelectorProxy`.

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

The payload is processed exactly like a network response: `@defer`, module-driven types, and data-driven dependencies all resolve normally. Use `@raw_response_type` on the query to generate the payload type.

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
