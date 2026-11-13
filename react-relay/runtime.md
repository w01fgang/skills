# Relay Runtime API

The `relay-runtime` package holds the Relay `Environment`, the `Store`, and the imperative APIs that work outside React hooks. This file documents those APIs.

## 1. Environment

The core of Relay's runtime is the `Environment`. The environment knows how to make requests to your GraphQL server and contains the `Store`, Relay's normalized data cache. Generally an application constructs a single environment and exposes it to all components via `RelayEnvironmentProvider`.

### Construction

To create an environment, provide a `Network` and a `Store`. The `Network` makes requests to your GraphQL server. The `Store` holds the normalized data cache.

```ts
import { Environment, Store, RecordSource, Network, FetchFunction } from "relay-runtime";

const HTTP_ENDPOINT = "https://graphql.org/graphql/";

const fetchGraphQL: FetchFunction = async (request, variables) => {
  const resp = await fetch(HTTP_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query: request.text, variables }),
  });
  if (!resp.ok) {
    throw new Error("Response failed.");
  }
  return await resp.json();
};

export const environment = new Environment({
  store: new Store(new RecordSource({})),
  network: Network.create(fetchGraphQL),
});
```

### Constructor options

The environment accepts additional optional configuration options.

| Option | Notes |
| --- | --- |
| `network` | Makes requests to the GraphQL server. Built with `Network.create(fetchFn)`. |
| `store` | Holds the normalized data cache. |
| `log` | A function that Relay calls with telemetry events. See the `LogEvent` types for the full list of events and their fields. |
| `missingFieldHandlers` | A list of handlers that Relay calls when a field is missing from the store. Use them to fulfill queries to fields like `Query.node` from cache. |
| `getDataID` | A function that Relay calls to generate a unique ID for an object. Use it when the server does not implement the Global Object Identification spec. |
| `relayFieldLogger` | A function that Relay calls when it encounters a field-level error (see section 11). |
| `deferDeduplicatedFields` | (v21 only) When `true`, Relay does not throw if a deferred response omits fields. The latest `@defer` spec proposal does not send duplicate fields in deferred responses. Relay does not support that proposal natively; use this option to transform responses into a format that Relay accepts. |

### `missingFieldHandlers` example

```js
const {ROOT_TYPE, Environment} = require('relay-runtime');

const missingFieldHandlers = [
  {
    handle(field, record, argValues): ?string {
      // Make sure to add a handler for the node field
      if (
        record != null &&
        record.getType() === ROOT_TYPE &&
        field.name === 'node' &&
        argValues.hasOwnProperty('id')
      ) {
        return argValues.id
      }
      return undefined;
    },
    kind: 'linked',
  },
];

const environment = new Environment({/*...*/, missingFieldHandlers});
```

- `missingFieldHandlers` is an array of handlers. Each handler specifies a `handle` function and the kind of missing fields it handles: `'scalar'` or `'linked'`.
- The `handle` function takes the missing field, the record that the field belongs to, and the arguments that the query passed to the field.
- For a `'scalar'` field, the `handle` function returns a scalar value. For a `'linked'` field, it returns an ID that references another object in the store.
- When Relay detects missing data while it fulfills a query from the local cache, it runs the matching handlers before it declares the data missing.

## 2. Store

The `Store` is the source of truth for application data. It holds the canonical set of records as a `RecordSource`.

### Store operations

- `lookup(selector)`: reads the results of a selector from the store.
- `subscribe(snapshot, callback)`: subscribes to changes to the results of a selector. The callback runs when published data changes the results of the snapshot's selector.
- `publish(source)`: updates the store with a `RecordSource`. Query, mutation, and subscription results and optimistic mutation updates all use this form.
- `notify()`: calls the `subscribe()` callbacks whose results changed because of intervening `publish()` calls.
- `retain(selector)`: keeps all records that the selector needs in memory. The records are not eligible for garbage collection until the returned reference is disposed.

### Store constructor options

The Relay Store accepts options that control garbage collection and staleness.

```js
const store = new Store(source, {gcScheduler});
```

```js
const store = new Store(source, {gcReleaseBufferSize: 10});
```

```js
const store = new Store(source, {queryCacheExpirationTime: 5 * 60 * 1000 });
```

| Option | Default | Purpose |
| --- | --- | --- |
| `gcScheduler` | `resolveImmediate` | A function that accepts a callback and schedules a garbage collection run. Provide one to make scheduling less aggressive, for example based on time or scheduler priorities. By convention, implementations do not execute the callback immediately. |
| `gcReleaseBufferSize` | `10` | The number of released queries that the Store keeps retained. With a size of 0, Relay collects queries immediately after release. |
| `queryCacheExpirationTime` | none | Age in ms after which a fetched query is stale. Without it, staleness checks look only at invalidated records. |
| `resolverContext` | none | Value that Relay passes to resolvers (see `resolvers.md`). Pass it to `RelayModernStore`. |

### `publish()` and `notify()`

- `publish(source)` updates the store with `source`. It does not call subscribers.
- `notify()` calls the subscribers whose results changed since the last `notify()`.
- Call `publish()` several times, then `notify()` once, to deliver many payloads in one subscriber pass.
- Merge rules of `publish()`: records that exist only in the source are added; records that exist in both are merged into a new record (inputs unchanged); records that are `null` in the source are deleted (set to null); records with the special sentinel value are removed (this undoes an optimistic record).
- `notify()` checks each subscription in 3 steps. First, it compares the changed record IDs with the IDs in the subscription's last `Snapshot`; no overlap skips the subscription. Second, it re-reads the overlapping subscriptions and compares the new result with the old one. Third, it calls the callback only when the result changed.

### Availability and invalidation

Relay does not consider data in the store stale, regardless of age, unless the data is marked as stale by the invalidation APIs or is older than the query cache expiration time.

A stale query is a query that Relay can fulfill with records from the store, and for which either of these holds:

- The time since Relay last fetched the query is greater than the query cache expiration time.
- The query contains at least one record that `invalidateStore()` or `invalidateRecord()` invalidated.

The staleness check occurs when Relay makes a new request (for example in a call to `loadQuery`). Components that reference stale data can still render that data. Requests that would use stale data go to the network.

The docs write `environment.check(query) === 'stale'`. The source returns an object with a `status` field, so compare `environment.check(operation).status === 'stale'`.

- `invalidateStore()` marks all data that the store holds at call time as stale.
- `record.invalidateRecord()` marks a record as stale. Queries that reference that record are stale.
- The hook `useSubscribeToInvalidationState` takes an array of IDs and a callback. The callback runs whenever the records for any of those IDs are marked as stale.

## 3. RecordSource and proxies

`RecordSource` is a collection of records keyed by their data ID. The store's record cache is a `RecordSource`.

Updater functions receive a proxy to the store. A mutation `updater` receives a `RecordSourceSelectorProxy`.

### `RecordSourceProxy`

The `RecordSourceProxy` serves as an interface to mutate records.

```javascript
interface RecordSourceProxy {
  create(dataID: DataID, typeName: string): RecordProxy;
  delete(dataID: DataID): void;
  get(dataID: DataID): ?RecordProxy;
  getRoot(): RecordProxy;
  invalidateStore(): void;
  readUpdatableFragment<TFragmentType: FragmentType, TData>(
    fragment: UpdatableFragment<TFragmentType, TData>,
    fragmentReference: HasUpdatableSpread<TFragmentType>,
  ): UpdatableData<TData>;
  readUpdatableQuery<TVariables: Variables, TData>(
    query: UpdatableQuery<TVariables, TData>,
    variables: TVariables,
  ): UpdatableData<TData>;
}
```

**Safety.** `RecordSourceProxy` exposes many low level APIs that are not typesafe. Consider typesafe updaters, optimistic updates, and Relay Resolvers instead if they cover your use case.

Behavior of `delete(dataID)`: for existing edges to the deleted record, `undefined` is returned in the default case even when the value is typed as non-nullable. When `@throwOnFieldError` is present, the missing data throws an error. `invalidateStore()` marks all data written before the call as stale for `environment.check()` and for a `store-or-network` fetch policy. `record.invalidateRecord()` does the same for the queries that reference that record.

### `RecordSourceSelectorProxy`

`RecordSourceSelectorProxy` is the type of the `store` that `updater` functions receive as an argument.

```javascript
interface RecordSourceSelectorProxy {
  create(dataID: string, typeName: string): RecordProxy;
  delete(dataID: string): void;
  get(dataID: string): ?RecordProxy;
  getRoot(): RecordProxy;
  getRootField(fieldName: string): ?RecordProxy;
  getPluralRootField(fieldName: string): ?Array<?RecordProxy>;
  invalidateStore(): void;
}
```

### `RecordProxy`

The `RecordProxy` serves as an interface to mutate records:

```javascript
interface RecordProxy {
  copyFieldsFrom(sourceRecord: RecordProxy): void;
  getDataID(): string;
  getLinkedRecord(name: string, arguments?: ?Object): ?RecordProxy;
  getLinkedRecords(name: string, arguments?: ?Object): ?Array<?RecordProxy>;
  getOrCreateLinkedRecord(
    name: string,
    typeName: string,
    arguments?: ?Object,
  ): RecordProxy;
  getType(): string;
  getValue(name: string, arguments?: ?Object): mixed;
  setLinkedRecord(
    record: RecordProxy,
    name: string,
    arguments?: ?Object,
  ): RecordProxy;
  setLinkedRecords(
    records: Array<?RecordProxy>,
    name: string,
    arguments?: ?Object,
  ): RecordProxy;
  setValue(value: mixed, name: string, arguments?: ?Object): RecordProxy;
  invalidateRecord(): void;
}
```

If a field takes arguments, pass a bag of variables as the last parameter.

## 4. ConnectionHandler

`ConnectionHandler` is a utility module exposed by `relay-runtime` that aids in the manipulation of connections.

```javascript
interface ConnectionHandler {
  getConnection(
    record: RecordProxy,
    key: string,
    filters?: ?Object,
  ): ?RecordProxy,
  createEdge(
    store: RecordSourceProxy,
    connection: RecordProxy,
    node: RecordProxy,
    edgeType: string,
  ): RecordProxy,
  insertEdgeBefore(
    connection: RecordProxy,
    newEdge: RecordProxy,
    cursor?: ?string,
  ): void,
  insertEdgeAfter(
    connection: RecordProxy,
    newEdge: RecordProxy,
    cursor?: ?string,
  ): void,
  deleteNode(connection: RecordProxy, nodeID: string): void
}
```

- `getConnection(record, key, filters)` retrieves a `RecordProxy` that represents a connection that a `@connection` directive annotated.
- `createEdge(store, connection, node, edgeType)` creates an edge.
- `insertEdgeBefore(connection, newEdge, cursor)` inserts the edge at the beginning of the connection, or before the specified `cursor`.
- `insertEdgeAfter(connection, newEdge, cursor)` inserts the edge at the end of the connection, or after the specified `cursor`.
- `deleteNode(connection, nodeID)` deletes any edges whose node ID matches the given ID.

```javascript
const user = store.get(userID);
const friends = ConnectionHandler.getConnection(user, 'FriendsFragment_friends');
const newFriend = store.get(newFriendId);
const edge = ConnectionHandler.createEdge(store, friends, newFriend, 'UserEdge');

// No cursor provided, append the edge at the end.
ConnectionHandler.insertEdgeAfter(friends, edge);

// No cursor provided, insert the edge at the front:
ConnectionHandler.insertEdgeBefore(friends, edge);
```

## 5. fetchQuery

Imperative query execution outside of React. `fetchQuery` returns an observable.

```js
// You should prefer passing an environment that was returned from useRelayEnvironment()
const MyEnvironment = require('MyEnvironment');
const {fetchQuery} = require('react-relay');

fetchQuery(
  environment,
  graphql`
    query AppQuery($id: ID!) {
      user(id: $id) {
        name
      }
    }
  `,
  {id: 4},
)
.subscribe({
  start: () => {...},
  complete: () => {...},
  error: (error) => {...},
  next: (data) => {...}
});
```

### Arguments

- `environment`: a Relay Environment instance to execute the request on.
- `query`: the GraphQL query to fetch, specified using a `graphql` template literal.
- `variables`: object with the variable values. These match the GraphQL variables declared in the query.
- `options` (optional):
  - `networkCacheConfig` (optional): object with cache config options. `force`: boolean; when `true`, Relay bypasses the network response cache. Defaults to `true`.
  - `fetchPolicy` (optional): determines whether `fetchQuery` reuses data that the local Relay store already holds. `"network-only"` (default) always issues a network request. `"store-or-network"` reuses data from the store if the full query is available locally, and issues a network request otherwise.

### Behavior

Docs: `api-reference/relay-runtime/fetch-query`.

- The request starts when you call `subscribe` or `toPromise`.
- Relay de-dupes identical network requests (same query and variables) that are in flight at the same time and that `fetchQuery` initiated.
- The `"store-and-network"` and `"store-only"` fetch policies are not supported, because `fetchQuery` issues a single network request and returns the response. The v20 docs omit `fetchPolicy`; the v20 source supports both values.
- The observer accepts `start(subscription)`, `next(data)`, `error(err)`, `complete()`, and `unsubscribe(subscription)`. `data` is a snapshot of the query data that Relay reads from the store when a payload arrives from the server. The subscription covers the fetch only, not later changes to the data in the store.
- `subscription.unsubscribe()` cancels the network request.
- `fetchQuery` saves the fetched data to the in-memory Relay store and notifies components subscribed to the relevant data. It does not retain the data, so the data can leave the store at any point after the request completes. To keep the data, call `environment.retain()` on the query.

### `.toPromise()`

`toPromise()` starts the query and returns a Promise that resolves when the first piece of data returns from the server. It cancels further processing, so deferred or 3D data in the query may not be processed. The docs recommend against `toPromise()`.

```js
const {fetchQuery} = require('react-relay');

fetchQuery(
  environment,
  graphql`
    query AppQuery($id: ID!) {
      user(id: $id) {
        name
      }
    }
  `,
  {id: 4},
)
.toPromise() // NOTE: don't use, this can cause data to be missing!
.then(data => {...})
.catch(error => {...};
```

The promise rejects when the request fails. You cannot cancel it.

### Retain a query

```js
// Retain query; this will prevent the data for this query and
// variables from being garbage collected by Relay
const disposable = environment.retain(queryDescriptor);

// Disposing of the disposable will release the data for this query
// and variables, meaning that it can be deleted at any moment
// by Relay's garbage collection if it hasn't been retained elsewhere
disposable.dispose();
```

## 6. commitMutation

Imperatively execute a mutation.

```js
import type {FeedbackLikeMutation} from 'FeedbackLikeMutation.graphql';
const React = require('React');

const {graphql, commitMutation} = require('react-relay');

function likeFeedback(environment: IEnvironment): Disposable {
  return commitMutation<FeedbackLikeMutation>(environment, {
    mutation: graphql`
      mutation FeedbackLikeMutation($input: FeedbackLikeData!) {
        feedback_like(data: $input) {
          feedback {
            id
            viewer_does_like
            like_count
          }
        }
      }
    `,
    variables: {
      input: {
        id: '123',
      },
    },
  });
}
```

### Config reference

`MutationConfig<TMutationConfig: MutationParameters>`:

| Field | Type | Notes |
| --- | --- | --- |
| `mutation` | `GraphQLTaggedNode` | A mutation specified using a GraphQL literal. |
| `variables` | `$ElementType<TMutationConfig, 'variables'>` | The variables to pass to the mutation. |
| `optimisticResponse` | object | Optional. An object whose type matches the raw response type of the mutation. Decorate the mutation with `@raw_response_type` when you use this field. |
| `optimisticUpdater` | `SelectorStoreUpdater` | Optional. A callback that runs when `commitMutation` is called, after Relay normalizes the `optimisticResponse` into the store. |
| `updater` | `SelectorStoreUpdater` | Optional. A callback that runs when a payload is received, after Relay writes the payload into the store. |
| `onCompleted` | `(response) => void` | Optional. A callback that runs when the mutation completes. |
| `onError` | `(Error) => void` | Optional. A callback that runs if the mutation results in an error. |
| `onUnsubscribe` | `() => void` | Optional. A callback that runs when the returned `Disposable` is disposed. |
| `cacheConfig` | `CacheConfig` | Optional. `force`, `poll`, `liveConfigId`, `metadata`, `transactionId`. |
| `uploadables` | `UploadableMap` | Optional. An object whose values are `File` or `Blob`. |

`SelectorStoreUpdater` is a function with the signature `(store: RecordSourceSelectorProxy, data) => void`. It imperatively writes and reads data to and from the Relay store.

### Disposable semantics

Docs: `api-reference/relay-runtime/commit-mutation`.

- `dispose()` before the request completes cancels and reverts any optimistic updates, prevents the `onCompleted` and `onError` callbacks, and calls `onUnsubscribe`. It does not necessarily cancel the network request.
- `dispose()` after the request completes does nothing.
- `onCompleted` receives the mutation fragment as Relay reads it from the store after the updaters and the declarative mutation directives ran. Data inside unmasked fragments is absent. Records that `@deleteRecord` deleted can be `null`.

### Updater execution

Docs: `guided-tour/updating-data/graphql-mutations`, `imperatively-modifying-store-data`.

1. If `optimisticResponse` is provided, Relay writes it into the store.
2. If `optimisticUpdater` is provided, Relay executes it.
3. If `optimisticResponse` was provided, Relay processes the declarative mutation directives on the optimistic response.
4. On success, Relay rolls back the optimistic updates, writes the server response to the store, executes `updater` if provided (the server payload is a root field in the store), processes the declarative mutation directives with the server response, and calls `onCompleted`.
5. On failure, Relay rolls back the optimistic updates and calls `onError`.

The list follows the docs. The source at tags v20.1.1 and v21.0.1 (`RelayPublishQueue.js`) contradicts the order in steps 2 to 4: the handlers of the declarative directives run before `optimisticUpdater` and before `updater`.

When another write updates the store while the mutation is in flight, Relay reverts the optimistic update, applies the new store update, and applies the optimistic update again.

When 2 optimistic responses change the same value and the first rolls back, the second stays applied and Relay does not recompute it. If 2 optimistic responses each raise a like count by 1, the like count stays raised by 2.

## 7. requestSubscription

Imperative API for establishing a GraphQL subscription.

```js
import {graphql, requestSubscription} from 'react-relay';

const subscription = graphql`
  subscription UserDataSubscription($input: InputData!) {
    # ...
  }
`;

function createSubscription(environment: IEnvironment): Disposable {
  return requestSubscription(environment, {
    subscription,
    variables: {input: {userId: '4'}},
  });
}
```

`requestSubscription` returns a `Disposable` that clears the subscription.

### Config reference

`GraphQLSubscriptionConfig<TSubscriptionPayload>`; docs: `api-reference/relay-runtime/request-subscription`.

| Field | Type | Notes |
| --- | --- | --- |
| `subscription` | `GraphQLTaggedNode` | A GraphQL subscription specified using a `graphql` template literal. |
| `variables` | object | The variables to pass to the subscription. |
| `onNext` | `(TSubscriptionPayload) => {}` | Optional. Runs when new data is received. |
| `onError` | `(Error) => {}` | Optional. Runs when an error occurs. |
| `onCompleted` | `() => void` | Optional. The docs say "when the subscription is established"; the source passes it as the `complete` handler, so it follows the source. |
| `updater` | `SelectorStoreUpdater` | Optional. Imperatively updates the store in response to the subscription payload. |
| `cacheConfig` | `CacheConfig` | Optional. |

## 8. commitLocalUpdate

Relay provides APIs for purely local updates to the Relay store, which are not tied to a server operation. Local data updates apply to client-only data and to regular data fetched from the server.

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

- `commitLocalUpdate` takes an environment and an updater function.
- `updater` takes a `store` argument, an instance of `RecordSourceSelectorProxy`. You can create new records, and update or delete existing ones.
- Unlike regular and optimistic updaters, the updater of `commitLocalUpdate` does not accept a second parameter, because there is no associated network response.
- Local data updates cause components subscribed to the data to be notified and to re-render.

`environment.commitPayload(operation, payload)` takes an `OperationDescriptor` and the payload for the query, and writes it to the Relay store. Relay resolves the payload like a normal server response for a query. Create `operation` with `createOperationDescriptor`, which takes the query and the query variables. Type the payload with the Flow type that the directive `@raw_response_type` on the query generates. Subscribed components re-render after the write.

For typed imperative edits, use an `@updatable` fragment with `readUpdatableFragment`:

```javascript
const fragment = graphql`
  fragment StoryLikeButton_updatable on Story @updatable {
    likeCount
    doesViewerLike
  }
`;
const {
  updatableData
} = store.readUpdatableFragment(
  fragment,
  story
);
updatableData.likeCount = updatableData.likeCount + 1
```

## 9. RelayEnvironmentProvider

`RelayEnvironmentProvider` sets a Relay environment in React Context. Usually a single instance of this component renders at the root of the application. Any Relay hook (like `useLazyLoadQuery` or `useFragment`) in a descendant of the provider uses the environment that the provider sets.

```js
const React = require('React');
const {
  Store,
  RecordSource,
  Environment,
  Network,
  Observable,
} = require("relay-runtime");

const {RelayEnvironmentProvider} = require('react-relay');

function fetchFunction(params, variables) {
  const response = fetch("http://my-graphql/api", {
    method: "POST",
    headers: [["Content-Type", "application/json"]],
    body: JSON.stringify({
      query: params.text,
      variables,
    }),
  });

  return Observable.from(response.then((data) => data.json()));
};

function createEnvironment() {
  const network = Network.create(fetchFunction);
  const store = new Store(new RecordSource());
  return new Environment({ store, network });
}

const environment = createEnvironment();

function Root() {
  return (
    <RelayEnvironmentProvider environment={environment}>
      <App />
    </RelayEnvironmentProvider>
  );
}

module.exports = Root;
```

Props:

| Prop | Notes |
| --- | --- |
| `environment` | The Relay environment to set in React Context. |

## 10. useRelayEnvironment

`useRelayEnvironment` accesses a Relay environment that a `RelayEnvironmentProvider` set.

```js
const React = require('React');

const {useRelayEnvironment} = require('react-relay');

function MyComponent() {
  const environment = useRelayEnvironment();

  const handler = useCallback(() => {
    // For example, can be used to pass the environment to functions
    // that require a Relay environment.
    commitMutation(environment, ...);
  }, [environment])

  return (...);
}

module.exports = MyComponent;
```

## 11. Field logger events

Source: docs `api-reference/relay-runtime/field-logger`; types in `store/RelayStoreTypes.js` (same in v20.1.1 and v21.0.1).

`relayFieldLogger` receives one event each time Relay handles a field-level error. Every event has `owner` (the fragment, query, or mutation name) and `fieldPath` (`.`-separated path from the owner to the field). Events that can throw also carry `handled`; throw your own error only when `handled` is `false`. A `@catch` directive or a nullable resolver sets `handled` to `true`.

| `kind` | Raised when | Extra fields |
| --- | --- | --- |
| `missing_expected_data.log` | Data that the operation requested is absent from the store. The field reads as `undefined`. | none |
| `missing_expected_data.throw` | Same, inside a `@throwOnFieldError` operation. Relay throws after the logger returns. | `handled` |
| `missing_required_field.log` | A `@required(action: LOG)` field is `null` or missing. | none |
| `missing_required_field.throw` | A `@required(action: THROW)` field is `null` or missing. | `handled` |
| `relay_resolver.error` | A Relay Resolver threw. Relay coerces the value to `null`. | `error`, `shouldThrow`, `handled` |
| `relay_field_payload.error` | The GraphQL response marked the field as an error. | `error`, `shouldThrow`, `handled` |

For `missing_expected_data`, `fieldPath` can end in `<record>` (an edge points to an ID that the store lacks) or `<abstract-type-hint>` (the compiler's virtual type-check field is missing).

## 12. `readInlineData`

The hooks APIs read data from the store only during the render phase. To read data outside the render phase, or outside React, annotate a fragment with `@inline` and read it with `readInlineData`.

```javascript
import {graphql, readInlineData} from 'react-relay';

// non-React function called from React
function processItemData(itemRef) {
  const item = readInlineData(
    graphql`
      fragment processItemData_item on Item @inline {
        title
        price
        creator {
          name
        }
      }
    `,
    itemRef,
  );
  sendToThirdPartyApi({
    title: item.title,
    price: item.price,
    creatorName: item.creator.name,
  });
}
```

Details of `@inline`: see `directives.md`.

## 13. `observeFragment` and `waitForFragmentData` (experimental)

Both functions read a fragment outside React. The docs mark both as experimental. They exist in v20.1.x and in v21.0.1 (`store/observeFragmentExperimental.js`, `store/waitForFragmentExperimental.js`; the v20 and v21 docs describe them in the same words). Import them from `relay-runtime/experimental`.

Both take `environment` as the first argument. The source signature is `(environment, fragment, fragmentRef)`. The docs examples omit `environment` and read `result.kind`. The source reads `state`, so write `result.state`.

```ts
import {observeFragment} from "relay-runtime/experimental";

const subscription = observeFragment(
  graphql`
    fragment TitleFragment on User {
      name
    }
  `,
  user,
).subscribe({
  next: (result) => {
    switch(result.kind) {
      case "loading":
        window.title = "...loading";
        break;
      case "error":
        window.title = "Oops, we hit an error";
        break;
      case "ok":
        window.title = `Welcome ${result.value.name}`;
        break;
    }
  }
});
subscription.unsubscribe();
```

```tsx
import { waitForFragmentData } from "relay-runtime/experimental";

const userData = await waitForFragmentData(
  graphql`
    fragment EventHandlerFragment on User {
      age
    }
  `,
  user,
);
```

| Function | Returns | States and behavior |
| --- | --- | --- |
| `observeFragment` | `Observable` | `{state: 'ok', value: T}`: data is available. `{state: 'error', error}`: network errors, `@throwOnFieldError`, or `@required(action: THROW)` field errors. `{state: 'loading'}`: the parent request or the current `@defer` payload is in flight, or a `@live` resolver is suspended. Emits again as the data changes. |
| `waitForFragmentData` | `Promise<T>` | Waits for network data and for `@live` resolvers to leave the suspended state. Rejects on a network error, `@throwOnFieldError`, or `@required(action: THROW)` field errors. |

With a plural fragment, `observeFragment` can notify the subscription several times, synchronously, for one store update that touches several list items. Debounce for one tick and use the last payload.

Known limits: a fragment with client edges throws `Client edges aren't supported yet.` in v20; v21 accepts them only when the fragment uses exec-time resolvers.
