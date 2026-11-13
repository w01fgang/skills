# Updating Data in Relay

Reference for mutating Relay's store: mutations, subscriptions, local updates, connection edits, and imperative store manipulation.

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

When data changes:

1. **Server response with `id`** — Relay merges the response fields into the existing record that has the same `id`. No updater needed.
2. **Changes more complex than field updates** (deleting records, adding items to collections) — Need either a declarative directive (`@appendEdge`, `@deleteRecord`, ...) or an imperative `updater` function.
3. **Purely local state** — Use `commitLocalUpdate` or updatable fragments/queries.

Components that subscribe to changed data re-render automatically.

---

## useMutation

```js
import type {FeedbackLikeMutation} from 'FeedbackLikeMutation.graphql';
const React = require('React');

const {graphql, useMutation} = require('react-relay');

function LikeButton() {
  const [commit, isInFlight] = useMutation<FeedbackLikeMutation>(graphql`
    mutation FeedbackLikeMutation($input: FeedbackLikeData!) {
      feedback_like(data: $input) {
        feedback {
          id
          viewer_does_like
          like_count
        }
      }
    }
  `);

  if (isInFlight) {
    return <Spinner />;
  }

  return (
    <button
      onClick={() => {
        commit({
          variables: {
            input: {
              id: '123',
              text: 'text',
            },
          },
          onCompleted(data) {
            console.log(data);
          },
        });
      }}
    />
  );
}
```

Returns a tuple: the commit callback and an in-flight boolean. The config object passed to `commit()` accepts:

| Option | Purpose |
|---|---|
| `variables` | Mutation variables (required) |
| `optimisticResponse` | Object that updates the local store immediately, before the mutation completes. Rolled back on error. |
| `optimisticUpdater` | Function that updates the local store immediately, before the mutation completes. |
| `updater` | Function that updates the local store based on the real server response |
| `onCompleted(response)` | Callback that runs when the request completes and the `updater` has updated the store |
| `onError(error)` | Callback that runs when Relay encounters an error during the request |
| `uploadables` | Optional map with 1 key per item. Each value is a `File` or `Blob`. |
| `onUnsubscribe` | Called when the returned `Disposable` is disposed |

### Callback and updater arguments

`commit()` returns a `Disposable`. `dispose()` reverts the optimistic update, and Relay does not update the store or call any success or error callback. The network request is not guaranteed to be cancelled. After the mutation succeeds, `dispose()` does not revert the store.

`isInFlight` is `true` while any mutation committed through the hook is in flight.

| Function | Arguments |
|---|---|
| `updater` | `(store: RecordSourceSelectorProxy, data?: TMutation['response'] \| null)` |
| `optimisticUpdater` | `(store)` |
| `onCompleted` | `(response)` |

- `data` holds the fields that the mutation selects directly. Fields that only a spread fragment selects are absent.
- `commitLocalUpdate` updaters take 1 parameter. No network payload exists.
- `onCompleted` receives the mutation selection read from the store after the updaters and the declarative directives run. Data from within unmasked fragments is not read. A record that `@deleteRecord` removed can be `null`.
- Relay can call `updater` and `optimisticUpdater` repeatedly. `onCompleted` runs once. Trigger side effects in `onCompleted`.

### Basic mutation

```js
const [commitMutation, isMutationInFlight] = useMutation(StoryLikeButtonLikeMutation);
function onLikeButtonClicked() {
  commitMutation({
    variables: {
      id: data.id,
    },
  })
}
const LikeButton = <button onClick={onLikeButtonClicked} disabled={isMutationInFlight}>Like</button>
```

`commitMutation` takes the variables that the mutation defines as an object.

---

## Auto-Merge by ID vs Updaters

Whenever the response includes an object with an `id` field, Relay checks if the store already contains a record with a matching `id`. If there is a match, Relay merges the other fields from the response into the existing record.

You **need an updater or directive** when:

- Inserting/removing items in a `@connection`.
- Deleting a record (`@deleteRecord` or imperative `store.delete(id)`).

### Auto-merge (no updater needed)

```js
const StoryLikeButtonLikeMutation = graphql`
  mutation StoreLikeButtonLikeMutation(
    // color1
    $id: ID!
  ) {
    // color2
    likeStory(
      id: $id
    ) {
      // color3
      story {
        likeCount
      }
    }
  }
`;
```

An example of a successful response for this mutation:

```json
{
  "likeStory": {
    "story": {
      "id": "34a8c",
      "likeCount": 47,
    }
  }
}
```

### Fragment-spread pattern

Spread the component fragment into the mutation response. Whenever the fragment changes in your code, the mutation returns the correct updated data. Spreading fragments is also preferable to refetching the data after a mutation completes, because the updated data arrives in a single round trip.

```
const StoryLikeButtonLikeMutation = graphql`
  mutation StoryLikeButtonLikeMutation(
    $id: ID,
  ) {
    likeStory(id: $id) {
      story {
        ...StoryLikeButtonFragment
      }
    }
  }
`;
```

---

## Optimistic Updates

Relay applies optimistic data before the network resolves. When the mutation succeeds or errors, Relay rolls back the optimistic data.

### optimisticResponse

Relay immediately writes the `optimisticResponse` data into the store. To Flow-type the field, pass a Flow type parameter to `useMutation` **and** decorate the mutation with `@raw_response_type`.

```js
import type {FeedbackLikeData, LikeButtonMutation} from 'LikeButtonMutation.graphql';
import type {LikeButton_feedback$fragmentType} from 'LikeButton_feedback.graphql';

const {useMutation, graphql} = require('react-relay');

function LikeButton({
  feedback: LikeButton_feedback$fragmentType,
}) {
  const data = useFragment(
    graphql`
      fragment LikeButton_feedback on Feedback {
        __id
        viewer_does_like @required(action: THROW)
        like_count @required(action: THROW)
      }
    `,
    feedback
  );

  const [commitMutation, isMutationInFlight] = useMutation<LikeButtonMutation>(
    graphql`
      mutation LikeButtonMutation($input: FeedbackLikeData!)
      @raw_response_type {
        feedback_like(data: $input) {
          feedback {
            viewer_does_like
            like_count
          }
        }
      }
    `
  );

  const changeToLikeCount = data.viewer_does_like ? -1 : 1;
  return <button
    onClick={() => commitMutation({
      variables: {
        input: {id: data.__id},
      },
      optimisticResponse: {
        feedback_like: {
          feedback: {
            id: data.__id,
            viewer_does_like: !data.viewer_does_like,
            like_count: data.like_count + changeToLikeCount,
          },
        },
      },
    })}
    disabled={isMutationInFlight}
  >
    Like
  </button>
}
```

### optimisticUpdater

Optimistic responses do not cover every case. Use `optimisticUpdater` to optimistically update data that the mutation does not select, or to add or remove items from a connection when the declarative mutation directives do not cover the use case. It is usually preferable to pass an `optimisticResponse`. An `optimisticUpdater` can often be the same function as `updater`.

### Execution order

1. If an `optimisticResponse` is provided, Relay writes that data into the store.
2. If an `optimisticUpdater` is provided, Relay runs it.
3. If an `optimisticResponse` was provided, Relay processes the declarative mutation directives on the optimistic response.
4. If the mutation request succeeds: Relay rolls back the optimistic update, writes the server response to the store, runs the `updater` (if provided), processes the declarative mutation directives using the server response, and calls `onCompleted`.
5. If the mutation request fails: Relay rolls back the optimistic update and calls `onError`.

Rollback rules:

- Relay reverts every optimistic change of a mutation when the response or the error arrives.
- If another write changes the store while the mutation is in flight, Relay reverts the optimistic update, applies the write, and re-applies the optimistic update.
- Relay does not recalculate a second optimistic value after the first one rolls back. With 2 optimistic responses that each add 1 to a like count, the first rollback leaves the count at +2. Use an optimistic updater when the value of the optimistic response depends on the store value and several optimistic responses can affect it.
- In the v20 and v21 source (`RelayPublishQueue`), the handlers behind the declarative directives (`@appendEdge`, `@deleteEdge`, ...) run before `optimisticUpdater` and before the real `updater`. The guided tour lists the updater first; the list above follows the guided tour.
- An optimistic response can contain the data for the full query response, including the content of fragment spreads. Components whose fragments are spread in an optimistic response can have inconsistent or partial data during an optimistic update.
- The type of the optimistic update includes the contents of all recursively nested fragments, so it can be very large. `@raw_response_type` on certain mutations can degrade the performance of the Relay compiler.

---

## Updating Connections

To modify a `@connection`, you need access to its connection record.

### Three ways to get the connection record

**1. `__id` from the fragment**:

```js
const fragmentData = useFragment(
  graphql`
    fragment StoryComponent_story on Story {
      comments @connection(key: "StoryComponent_story_comments_connection") {
        # Query for the __id field
        __id

        # ...
      }
    }
  `,
  props.story,
);

// Get the connection record id
const connectionID = fragmentData?.comments?.__id;
```

Then use it to access the record in the store:

```js
function updater(store: RecordSourceSelectorProxy) {
  // connectionID is passed as input to the mutation/subscription
  const connection = store.get(connectionID);

  // ...
}
```

The `__id` field is not something that your GraphQL API needs to expose. Relay adds it automatically to identify the connection record.

**2. `ConnectionHandler.getConnectionID`**, when you have the ID of the parent record:

```js
const {ConnectionHandler} = require('relay-runtime');

function updater(store: RecordSourceSelectorProxy) {
  // Get the connection ID
  const connectionID = ConnectionHandler.getConnectionID(
    storyID, // passed as input to the mutation/subscription
    'StoryComponent_story_comments_connection',
  );

  // Get the connection record
  const connectionRecord = store.get(connectionID);

  // ...
}
```

**3. `ConnectionHandler.getConnection`**, when you have the parent record:

```js
const {ConnectionHandler} = require('relay-runtime');

function updater(store: RecordSourceSelectorProxy) {
  // Get parent story record
  // storyID is passed as input to the mutation/subscription
  const storyRecord = store.get(storyID);

  // Get the connection record from the parent
  const connectionRecord = ConnectionHandler.getConnection(
    storyRecord,
    'StoryComponent_story_comments_connection',
  );

  // ...
}
```

### Connection identity and filters

If you declare a connection that takes arguments as filters, the values of the filters are part of the connection identifier. Each of the values passed as connection filters identifies the connection in the Relay store. This excludes the pagination arguments `first`, `last`, `before` and `after`.

```js
const {graphql} = require('RelayModern');

const storyFragment = graphql`
  fragment StoryComponent_story on Story {
    comments(
      order_by: $orderBy,
      filter_mode: $filterMode,
      language: $language,
    ) @connection(key: "StoryComponent_story_comments_connection") {
      edges {
        nodes {
          body {
            text
          }
        }
      }
    }
  }
`;
```

Whatever values you used for `$orderBy`, `$filterMode` and `$language` when you queried the `comments` field are part of the connection identifier. Pass a third argument to `ConnectionHandler.getConnection` with the concrete filter values:

```js
const {ConnectionHandler} = require('RelayModern');

function updater(store: RecordSourceSelectorProxy) {
  const storyRecord = store.get(storyID);

  // Get the connection instance for the connection with comments sorted
  // by the date they were added
  const connectionRecordSortedByDate = ConnectionHandler.getConnection(
    storyRecord,
    'StoryComponent_story_comments_connection',
    {order_by: '*DATE_ADDED*', filter_mode: null, language: null}
  );
```

### ConnectionHandler — imperative edits

The directives in the next section largely remove the need to add and remove items from a connection by hand. An updater gives more control and covers more use cases.

Read the edge from the mutation payload, and build an edge to add to the connection with `ConnectionHandler.buildConnectionEdge`:

```js
const {ConnectionHandler} = require('relay-runtime');

function updater(store: RecordSourceSelectorProxy) {
  const storyRecord = store.get(storyID);
  const connectionRecord = ConnectionHandler.getConnection(
    storyRecord,
    'StoryComponent_story_comments_connection',
  );

  // Get the payload returned from the server
  const payload = store.getRootField('comment_create');

  // Get the edge inside the payload
  const serverEdge = payload.getLinkedRecord('comment_edge');

  // Build edge for adding to the connection
  const newEdge = ConnectionHandler.buildConnectionEdge(
    store,
    connectionRecord,
    serverEdge,
  );

  // ...
}
```

To create a new edge from scratch, use `ConnectionHandler.createEdge`:

```js
const {ConnectionHandler} = require('relay-runtime');

function updater(store: RecordSourceSelectorProxy) {
  const storyRecord = store.get(storyID);
  const connectionRecord = ConnectionHandler.getConnection(
    storyRecord,
    'StoryComponent_story_comments_connection',
  );

  // Create a new local Comment record
  const id = `client:new_comment:${randomID()}`;
  const newCommentRecord = store.create(id, 'Comment');

  // Create new edge
  const newEdge = ConnectionHandler.createEdge(
    store,
    connectionRecord,
    newCommentRecord,
    'CommentEdge', /* GraphQl Type for edge */
  );

  // ...
}
```

Add the edge with `ConnectionHandler.insertEdgeAfter` or `ConnectionHandler.insertEdgeBefore`. These APIs mutate the connection in place.

```js
const {ConnectionHandler} = require('relay-runtime');

function updater(store: RecordSourceSelectorProxy) {
  const storyRecord = store.get(storyID);
  const connectionRecord = ConnectionHandler.getConnection(
    storyRecord,
    'StoryComponent_story_comments_connection',
  );

  const newEdge = (...);

  // Add edge to the end of the connection
  ConnectionHandler.insertEdgeAfter(
    connectionRecord,
    newEdge,
  );

  // Add edge to the beginning of the connection
  ConnectionHandler.insertEdgeBefore(
    connectionRecord,
    newEdge,
  );
}
```

`ConnectionHandler.deleteNode` removes an edge from a connection:

```javascript
const user = store.get(userID);
const friends = ConnectionHandler.getConnection(user, 'FriendsFragment_friends');
ConnectionHandler.deleteNode(friends, idToDelete);
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

The directives `@appendEdge`, `@prependEdge`, `@appendNode`, `@prependNode` and `@deleteEdge` add and remove items on a connection. They work on mutation, subscription and query fields. They accept a `connections` parameter: a GraphQL variable that contains an array of connection IDs. Connection IDs come from the `__id` field of the connection or from `ConnectionHandler.getConnectionID`.

### @appendEdge / @prependEdge

Work on a field with a single edge or a list of edges. `@prependEdge` adds the selected edges to the beginning of each connection in the `connections` array. `@appendEdge` adds them to the end.

```graphql
mutation AppendCommentMutation(
  # Define a GraphQL variable for the connections array
  $connections: [ID!]!
  $input: CommentCreateInput
) {
  commentCreate(input: $input) {
    # Use @appendEdge or @prependEdge on the edge field
    feedbackCommentEdge @appendEdge(connections: $connections) {
      cursor
      node {
        id
      }
    }
  }
}
```

### @appendNode / @prependNode

Work on a field with a single node or a list of nodes. They create edges with the specified `edgeTypeName`.

```graphql
mutation AppendCommentMutation(
  # Define a GraphQL variable for the connections array
  $connections: [ID!]!
  $input: CommentCreateInput
) {
  commentCreate(input: $input) {
    # Use @appendNode or @prependNode on the node field
    feedbackCommentNode @appendNode(connections: $connections, edgeTypeName: "CommentsEdge") {
      id
    }
  }
}
```

### @deleteEdge

Works on GraphQL fields that return an `ID` or `[ID]`. Deletes the edges whose nodes match the `id` from each connection in the `connections` array.

```graphql
mutation DeleteCommentsMutation(
  # Define a GraphQL variable for the connections array
  $connections: [ID!]!
  $input: CommentsDeleteInput
) {
  commentsDelete(input: $input) {
    deletedCommentIds @deleteEdge(connections: $connections)
  }
}
```

### @deleteRecord

Add `@deleteRecord` to the deleted ID to delete an item from the store in response to a mutation. See `directives.md`.

```graphql
mutation DeletePostMutation($input: DeletePostData!) {
  delete_post(data: $input) {
    deleted_post {
      id @deleteRecord
    }
  }
}
```

### Directive behavior

- The directives also work on query fields.
- Relay applies the directives to the `optimisticResponse` first, then to the server response. If the mutation fails, Relay rolls back the updates from `@prependEdge`, `@appendEdge`, `@prependNode` and `@appendNode`.

---

## Imperative Store API

Updater functions receive a store proxy. Three proxy types:

- **`RecordSourceSelectorProxy`** — the `store` that mutation and subscription `updater` functions receive. Has `getRootField` and `getPluralRootField` in addition to source methods. The docs (`local-data-updates`) name this type for `commitLocalUpdate` too. The source at tags v20.1.1 and v21.0.1 (`RelayStoreTypes.js`, `StoreUpdater`) contradicts the docs: the `commitLocalUpdate` updater receives a `RecordSourceProxy`.
- **`RecordSourceProxy`** — the interface to mutate records. It has no root-field helpers. It exposes many low-level APIs that are not typesafe.
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

### Arguments on fields

If the field takes arguments, pass a bag of `variables`:

```javascript
const name = viewer.getValue('name', {arg: 'value'});
```

---

## commitLocalUpdate

Pure client-side store edits — no network. `commitLocalUpdate` takes an environment and an updater function. The docs name the `store` argument of the updater `RecordSourceSelectorProxy`; the source type is `RecordSourceProxy` (see the note in the proxy list above). The updater does not accept a second parameter, because there is no network response.

```js
import type {Environment} from 'react-relay';

const {commitLocalUpdate, graphql} = require('react-relay');

function commitCommentCreateLocally(
  environment: Environment,
  feedbackID: string,
) {
  return commitLocalUpdate(environment, store => {
    // Imperatively mutate the store here
  });
}

module.exports = {commit: commitCommentCreateLocally};
```

Local data updates cause components that subscribe to the data to re-render. They work on client-only data and on data that an operation fetched from the server.

---

## useSubscription

Hook to subscribe and unsubscribe to a subscription. A subscription looks like a query, with the `subscription` keyword. The declarative mutation directives and `@deleteRecord` work in subscriptions.

```js
import {graphql, useSubscription} from 'react-relay';
import {useMemo} from 'react';

const subscription = graphql`
  subscription UserDataSubscription($input: InputData!) {
    # ...
  }
`;

function UserComponent({ id }) {
  // IMPORTANT: your config should be memoized.
  // Otherwise, useSubscription will re-render too frequently.
  const config = useMemo(() => ({
    variables: {id},
    subscription,
  }), [id, subscription]);

  useSubscription(config);

  return (/* ... */);
}
```

Config options: `subscription`, `variables`, `updater`, `onNext`, `onError`, `onCompleted`, `cacheConfig`.

---

## commitPayload

Writes a payload for a query into the store. `commitPayload` takes an `OperationDescriptor` and the payload. Relay resolves the payload like a normal server response for a query, and also resolves Data Driven Dependencies.

```js
import type {FooQueryRawResponse} from 'FooQuery.graphql'

const {createOperationDescriptor} = require('relay-runtime');

const operationDescriptor = createOperationDescriptor(FooQuery, {
  id: 'an-id',
  otherVariable: 'value',
});

const payload: FooQueryRawResponse = {...};

environment.commitPayload(operationDescriptor, payload);
```

`createOperationDescriptor` takes the query and the query variables. Add `@raw_response_type` to the query to generate the Flow type of the payload.

---

## Typesafe Updaters

Typesafe updaters are a typesafe alternative to the imperative store APIs. You write an updatable query or fragment that specifies the data to update. You read that data from the store, which returns an **updatable proxy**. Mutating the updatable proxy with setters (`updatableData.name = "Godzilla"`) calls the old API with added type safety. The API is identical on v20 and v21.

| Directive | Where | Purpose |
|---|---|---|
| `@updatable` | query, fragment definition | Selects the fields that an updater reads and writes. Relay never fetches them. |
| `@assignable` | fragment definition | Marks a type that a linked field accepts. The fragment contains only `__typename`. |

`readUpdatableFragment(fragment, ref)` and `readUpdatableQuery(query, variables)` exist on `RecordSourceProxy` and `RecordSourceSelectorProxy`. Both return `{ updatableData }`. Assigning to a property of `updatableData` writes to the store.

### Scalar fields

```js
// CreateFeedback.js
import type {Environment} from 'react-relay';
import type {
  FeedbackCreateData,
  CreateFeedbackMutation,
  CreateFeedbackMutation$data,
} from 'CreateFeedbackMutation.graphql';

const {commitMutation, graphql} = require('react-relay');
const {ConnectionHandler} = require('relay-runtime');

function commitCreateFeedbackMutation(
  environment: Environment,
  input: FeedbackCreateData,
) {
  return commitMutation<FeedbackCreateData>(environment, {
    mutation: graphql`
      mutation CreateFeedbackMutation($input: FeedbackCreateData!) {
        feedback_create(input: $input) {
          feedback {
            id
            # Step 1: in the mutation response, spread an updatable fragment (defined below).
            # This updatable fragment will select the fields that we want to update on this
            # particular feedback object.
            ...CreateFeedback_updatable_feedback
          }
        }
      }
    `,
    variables: {input},

    // Step 2: define an updater
    updater: (store: RecordSourceSelectorProxy, response: ?CreateCommentMutation$data) => {
      // Step 3: Access and nullcheck the feedback object.
      // Note that this could also have been achieved with the @required directive.
      const feedbackRef = response?.feedback_create?.feedback;
      if (feedbackRef == null) {
        return;
      }

      // Step 3: call store.readUpdatableFragment
      const {updatableData} = store.readUpdatableFragment(
          // Step 4: Pass it a fragment literal, where the fragment contains the @updatable directive.
          // This fragment selects the fields that you wish to update on the feedback object.
          // In step 1, we spread this fragment in the query response.
          graphql`
            fragment CreateFeedback_updatable_feedback on Feedback @updatable {
              is_new_comment
            }
          `,
          // Step 5: Pass the fragment reference.
          feedbackRef
        );

      // Step 6: Mutate the updatableData object!
      updatableData.is_new_comment = true;
    },
  });
}

module.exports = {commit: commitCreateFeedbackMutation};
```

`readUpdatableQuery` needs no fragment reference:

```js
// NameUpdater.react.js
function NameUpdater({ queryRef }: {
  queryRef: NameUpdater_viewer$key,
}) {
  const environment = useRelayEnvironment();
  const data = useFragment(
    graphql`
      fragment NameUpdater_viewer on Viewer {
        name
      }
    `,
    queryRef
  );
  const [newName, setNewName] = useState(data?.viewer?.name);
  const onSubmit = () => {
    commitLocalUpdate(environment, store => {
      const {updatableData} = store.readUpdatableQuery(
        graphql`
          query NameUpdaterUpdateQuery @updatable {
            viewer {
              name
            }
          }
        `,
        {}
      );
      const viewer = updatableData.viewer;
      if (viewer != null) {
        viewer.name = newName;
      }
    });
  };

  // etc
}
```

Prefer `readUpdatableQuery` when:

- You have no ready access to a fragment reference, for example when the call to `commitLocalUpdate` is not associated with a component.
- You have no ready access to a fragment that selects the parent record of the record you modify (for example the `Query`). Updatable fragments cannot be spread at the top level.
- You want to use variables in the updatable fragment. Updatable fragments reuse the variables that were passed to the query.

### Rules

- The server does not know about updatable queries and fragments. Relay never fetches their fields, even when a regular query or fragment spreads the updatable fragment. To fetch and mutate a field, select it in both a regular query or fragment and an updatable query or fragment.
- Updatable data can be missing when the store does not hold it.
- You cannot spread regular fragments in updatable queries and fragments.
- `@defer` and similar directives are not allowed in updatable queries and fragments.

### Linked fields

An assignment to a linked field needs an `@assignable` fragment. The fragment is spread at the source (the new value) and at the destination (the linked field in the updatable query or fragment):

```js
// AssignBestFriendButton.react.js
import type {AssignBestFriendButton_user$key} from 'AssignBestFriendButton_user.graphql';
import type {RecordSourceSelectorProxy} from 'react-relay';

const {commitLocalUpdate, useFragment, useRelayEnvironment} = require('react-relay');

graphql`
  fragment AssignBestFriendButton_assignable_user on User @assignable {
    __typename
  }
`;

export default function AssignBestFriendButton({
  someTypeRef: AssignBestFriendButton_someType$key,
}) {
  const data = useFragment(graphql`
    fragment AssignBestFriendButton_someType on SomeType {
      user {
        name
        ...AssignBestFriendButton_assignable_user
      }
    }
  `, someTypeRef);

  const environment = useRelayEnvironment();
  const onClick = () => {
    const updatableData = commitLocalUpdate(
      environment,
      (store: RecordSourceSelectorProxy) => {
        const {updatableData} = store.readUpdatableQuery(
            graphql`
              query AssignBestFriendButtonUpdatableQuery
              @updatable {
                viewer {
                  best_friend {
                    ...AssignBestFriendButton_assignable_user
                  }
                }
              }
            `,
            {}
          );

        if (data.user != null && updatableData.viewer != null) {
          updatableData.viewer.best_friend = data.user;
        }
      }
    );
  };

  return (<button onClick={onClick}>
    Declare {user.name ?? 'someone with no name'} my best friend!
  </button>);
}
```

- The source of the assignment is a user where an assignable fragment is spread. The target field must have the same assignable fragment spread.
- The query passed to `readUpdatableQuery` must include the `@updatable` directive.
- Every assigned linked field (the right-hand side of the assignment) must originate in a read-only fragment, query, mutation or subscription. `updatableData.foo = updatableData.foo` is invalid.
- To append to a list, select the existing list from a read-only fragment (with the assignable fragment spread on its items) and assign `viewer.best_friends = [...viewer.best_friends, data.user]`.
- Assigning `null` to a linked field sets the link to `null` in the store. Check for `null` before the assignment.
- The assigned object has no guarantee about which fields are present. A consumer of an updated field cannot assume that its required fields were fetched.
- To assign from an abstract field (for example `Node`) to a concrete field (for example `User`), refine the type with an inline fragment and check `__typename`:

```js
const data = useFragment(graphql`
  fragment AssignBestFriendButton_someType on Query {
    node(id: "4") {
      ... on User {
        __typename
        ...AssignBestFriendButton_assignable_user
      }
    }
  }
`, queryRef);

const environment = useRelayEnvironment();
const onClick = () => {
  const updatableData = commitLocalUpdate(
    environment,
    (store: RecordSourceSelectorProxy) => {
      const {updatableData} = store.readUpdatableQuery(
          graphql`
            query AssignBestFriendButtonUpdatableQuery
            @updatable {
              viewer {
                best_friend {
                  ...AssignBestFriendButton_assignable_user
                }
              }
            }
          `,
          {}
        );

      if (data.node != null && data.node.__typename === "User" && updatableData.viewer != null) {
        updatableData.viewer.best_friend = data.node;
      }
    }
  );
};
```

- Assignment to a field with an interface type (for example `Actor`) is straightforward when the source is guaranteed to implement the interface: the source has the same interface type, or a concrete type that implements it.
- When the source type (for example `Node`) is not known to implement the interface, the compiler emits an optional `__isFoo_actor?: string` field, and the assignment does not type-check. Each generated artifact exports a `validate` function that checks for the `__isFoo_actor` field. It returns the object with a valid type for the assignment, or `false`:

```js
import {validate as validateActor} from 'Foo_actor.graphql';

graphql`
  fragment Foo_actor on Actor @assignable {
    __typename
  }
`;

const data = useFragment(graphql`
  fragment Foo_query on Query {
    node(id: "4") {
      ...Foo_actor
    }
  }
`, queryRef);

const environment = useRelayEnvironment();
const onClick = () => {
  commitLocalUpdate(environment, store => {
    const {updatableData} = store.readUpdatableQuery(
      graphql`
        query FooUpdatableQuery @updatable {
          viewer {
            actor {
              ...Foo_actor
            }
          }
        }
      `,
      {}
    );

    if (updatableData.viewer != null && data.node != null) {
      const validActor = validateActor(data.node);
      if (validActor !== false) {
        updatableData.viewer.actor = validActor;
      }
    }
  });
};
```

---

## Client-Only Data

Client schema extensions add fields and types that the server does not define. Reference the `.graphql` file in the `"schemaExtensions"` of your Relay config, either directly or through its folder.

```graphql
type Note {
  id: ID!
  title: String
  body: String
}
```

```graphql
extend type User {
  notes: [Note]
}
```

- A query that reads local data needs at least 1 server field. An introspection field such as `__typename` counts. A query with only client fields uses `useClientQuery`.
- New client-side schema fields default to `undefined`. Prime the initial local state with `commitLocalUpdate`:

```javascript
import {commitLocalUpdate} from 'react-relay';

commitLocalUpdate(environment, store => {
  const user = store.getRoot().getLinkedRecord('viewer');

  // initialize user notes to an empty array.
  user.setLinkedRecords([], 'notes');
});
```

- Create a client record with an ID such as `client:Note:<n>`:

```javascript
import {commitLocalUpdate} from 'react-relay';

let tempID = 0;

function createUserNote(environment) {
  commitLocalUpdate(environment, store => {
    const user = store.getRoot().getLinkedRecord('viewer');
    const userNoteRecords = user.getLinkedRecords('notes') || [];

    // Create a unique ID.
    const dataID = `client:Note:${tempID++}`;

    //Create a new note record.
    const newNoteRecord = store.create(dataID, 'Note');

    // Add the record to the user's list of notes.
    user.setLinkedRecords([...userNoteRecords, newNoteRecord], 'notes');
  });
}
```

- A query that a component renders with `useLazyLoadQuery` retains its data. If no component renders the local data, call `environment.retain()` with an operation that references the record. Dispose of the result when Relay can garbage collect the data.
- To delete a client record, remove it from the parent list and delete it from the store:

```javascript
import {commitLocalUpdate} from 'react-relay';

function deleteUserNote(environment, dataID) {
  commitLocalUpdate(environment, store => {
    const user = store.getRoot().getLinkedRecord('viewer');
    const userNoteRecords = user.getLinkedRecords('notes');

    // Remove the note from the list of user notes.
    const newUserNoteRecords = userNoteRecords.filter(x => x.getDataID() !== dataID);

    // Delete the note from the store.
    store.delete(dataID);

    // Set the new list of notes.
    user.setLinkedRecords(newUserNoteRecords, 'notes');
  });
}
```

- Mutation and subscription updaters can also update client-only data.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| New item not showing in list | List is a `@connection` and mutation didn't touch it | Add `@appendEdge`/`@appendNode` or write an `updater` |
| Declarative directive did nothing | `connections` variable empty or wrong connection ID | Read `data.yourConnection.__id` and pass in `[ID!]!` variable |
| Connection updates wrong list after filter change | The filter values are part of the connection identity | Pass the same filter values to `ConnectionHandler.getConnection` |
| `ConnectionHandler.getConnection` returns null | Wrong key, wrong parent record, or missing filter values | Match `key` exactly and pass the same filters used in the fragment |
| `optimisticResponse` type error | Missing `@raw_response_type` on the mutation | Add the directive; regenerate types |
| Two optimistic responses stomping each other | Overlapping optimistic writes on same fields | Use an optimistic updater that computes the value from the store |
| Record stale after external change | Store thinks data fresh | Call `record.invalidateRecord()` or `store.invalidateStore()` |
| Client-only field reads `undefined` | No updater wrote the field yet | Prime it with `commitLocalUpdate` |
| Query with only client fields misbehaves under `useLazyLoadQuery` | A query that reads local data needs at least 1 server field | Add a server field such as `__typename`, or use `useClientQuery` |
| Updatable field is `undefined` after `readUpdatableFragment` | Relay never fetches updatable fields | Select the field in a regular query or fragment too |
| Like count stays +2 after one optimistic rollback | Relay does not recalculate later optimistic values | Use an optimistic updater that computes the value from the store |
| `updater` argument `data` is `null` | Mutation returned no data | Guard with `data?.field` |
