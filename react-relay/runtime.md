# Relay Runtime API

The `relay-runtime` package exposes the imperative core that sits below the React hooks. Hooks are the preferred way to read/write data from components — the runtime APIs exist for the cases hooks cannot serve: bootstrapping the Environment, orchestrating side effects outside React, SSR, imperative prefetching, writing store updaters, and authoring utility modules (e.g. publish/subscribe bridges).

This file documents those APIs.

## 1. Environment

The `Environment` is the root object wiring together network, store, handlers, and logging. It is the single argument every imperative runtime API takes.

### Construction

```ts
import {
  Environment,
  Network,
  RecordSource,
  Store,
  Observable,
  type GraphQLResponse,
  type RequestParameters,
  type Variables,
  type HandlerProvider,
  type MissingFieldHandler,
  type LogRequestInfoFunction,
} from 'relay-runtime';

function fetchFn(
  params: RequestParameters,
  variables: Variables,
): Observable<GraphQLResponse> {
  return Observable.create((sink) => {
    fetch('/graphql', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({query: params.text, variables}),
    })
      .then((r) => r.json())
      .then((json) => {
        sink.next(json);
        sink.complete();
      })
      .catch(sink.error);
  });
}

export const environment = new Environment({
  network: Network.create(fetchFn),
  store: new Store(new RecordSource()),
  isServer: typeof window === 'undefined',
  treatMissingFieldsAsNull: false,
});
```

### Constructor options

| Option | Type | Purpose |
| --- | --- | --- |
| `network` | `INetwork` | Required. Executes queries, mutations, subscriptions. Built with `Network.create(fetch, subscribe?)`. |
| `store` | `Store` | Optional. Defaults to a new `RelayModernStore`. Holds normalized records and tracks subscribers. |
| `handlerProvider` | `(handle: string) => Handler` | Maps `@__clientField(handle: "...")` / connection handles to runtime handlers. Defaults to `RelayDefaultHandlerProvider`. |
| `operationLoader` | `{ get(ref): ?Node; load(ref): Promise<?Node> }` | Required if using `@module` / 3D. Resolves split operations lazily. |
| `missingFieldHandlers` | `MissingFieldHandler[]` | Lets Relay satisfy missing scalars / linked records from adjacent data (e.g. treat `node(id:$x)` as already cached if `User:$x` exists). |
| `isServer` | `boolean` | Disables client-only optimizations; set `true` during SSR. |
| `treatMissingFieldsAsNull` | `boolean` | If `true`, the response normalizer writes `null` for each field that the response omits. Set it when the server skips fields with `null` values. With `false`, the normalizer leaves the field unset and logs a dev warning. |
| `log` | `(event: LogEvent) => void` | Receives lifecycle events: `queryresource.fetch`, `network.start/next/complete/error`, `execute.start/next.start/next.end/error/complete`, `store.publish`, `store.gc.start/interrupted/end`, etc. Use for metrics. |
| `relayFieldLogger` | `(event) => void` | Receives field events: `missing_required_field.log` / `.throw`, `missing_expected_data.log` / `.throw`, `relay_resolver.error`, `relay_field_payload.error`. |
| `scheduler` | `TaskScheduler` | Custom scheduler for batching store notifications (e.g. `unstable_batchedUpdates`). |
| `getDataID` | `(fieldValue, typeName) => string` | Override Relay's default identity (default reads `id`). Useful for composite keys. |
| `UNSTABLE_defaultRenderPolicy` | `'partial' \| 'full'` | Toggles whether partial store data satisfies a read. Default: `'partial'`. |
| `configName` | `string` | Label stored on `environment.configName`. |
| `normalizeResponse` | `NormalizeResponseFunction` | Replaces the built-in response normalizer. |
| `operationTracker` | `OperationTracker` | Tracks in-flight operations. Default: a new `RelayOperationTracker`. |
| `options` | `unknown` | Opaque value stored on `environment.options`. The Environment does not read it. |
| `shouldProcessClientComponents` | `boolean` | Passed to the operation executor. Also passed to the default Store (see below). |
| `deferDeduplicatedFields` | `boolean` | (v21 only) When `true`, Relay does not throw if a deferred response omits fields that an earlier payload already sent. The latest `@defer` spec proposal omits such fields. Relay does not support that proposal natively; use this option with a response transform. |

Source: `EnvironmentConfig` in `packages/relay-runtime/store/RelayModernEnvironment.js`. All options except `network` are optional. When you omit `store`, the Environment creates `new Store(new RecordSource(), {getDataID, log, operationLoader, shouldProcessClientComponents})` from its own config. When you pass `store`, the Environment does not forward these four options to it; set them on the `Store` constructor.

### `missingFieldHandlers` example

```ts
const handlers: MissingFieldHandler[] = [
  {
    kind: 'linked',
    handle(field, record, args, store) {
      if (
        record != null &&
        record.getType() === ROOT_TYPE &&
        field.name === 'node' &&
        args.id != null
      ) {
        return args.id; // satisfy node(id:) from any cached record with that id
      }
      return undefined;
    },
  },
];
```

## 2. Store

`Store` wraps a `RecordSource` and coordinates retention, GC, and subscriptions.

```ts
const source = new RecordSource();      // in-memory normalized record map
const store = new Store(source, {
  gcScheduler: (run) => setTimeout(run, 0),
  gcReleaseBufferSize: 10,               // retain N most-recent released ops
  queryCacheExpirationTime: 5 * 60_000, // ms before cached ops are invalidated
});
```

### Store constructor options

Source: `RelayModernStore.js` constructor, same in v20.1.1 and v21.0.1 except where marked. `Store` from `relay-runtime` is `RelayModernStore`. `LiveResolverStore` is a backward-compatible alias of the same class.

| Option | Type | Default | Purpose |
| --- | --- | --- | --- |
| `gcScheduler` | `(run: () => void) => void` | `resolveImmediate` | Schedules each GC run. |
| `gcReleaseBufferSize` | `number` | `10` | Number of released operations that the Store keeps before it collects the oldest. |
| `queryCacheExpirationTime` | `number` (ms) | none | Age after which `check()` reports a fetched operation as `stale`. |
| `log` | `LogFunction` | none | Receives store events. |
| `operationLoader` | `OperationLoader` | none | Loads split operations for `@module`. |
| `getDataID` | `GetDataID` | `defaultGetDataID` | Computes record IDs. |
| `shouldProcessClientComponents` | `boolean` | `false` | Enables client-component payload handling. |
| `resolverContext` | `ResolverContext` | none | Value passed to every Relay Resolver (see `resolvers.md`). |
| `shouldRetainWithinTTL_EXPERIMENTAL` | `boolean` | `false` | Experimental. Keeps expired or evicted operation roots in the Store; the Store does not delete them. |
| `treatMissingFieldsAsNull` | `boolean` | `false` | Used only when Relay normalizes `@outputType` resolver payloads. |
| `deferDeduplicatedFields` | `boolean` | `false` | (v21 only) Same meaning as the Environment option. Used only for `@outputType` resolver payloads. |
| `actorIdentifier` | `ActorIdentifier` | none | Used only for `@outputType` resolver payloads. |


```ts
interface Store {
  // Retention & GC
  retain(operation: OperationDescriptor): Disposable;
  holdGC(): Disposable;          // pause garbage collection
  check(operation): OperationAvailability; // {status: 'available', fetchTime} | {status: 'stale'} | {status: 'missing'}

  // Reads
  lookup(selector: SingularReaderSelector): Snapshot;
  subscribe(snapshot: Snapshot, cb: (next: Snapshot) => void): Disposable;

  // Writes
  publish(source: RecordSource, idsMarkedForInvalidation?: Set<DataID>): void;
  notify(
    sourceOperation?: OperationDescriptor,
    invalidateStore?: boolean,
  ): ReadonlyArray<RequestDescriptor>;

  // Persistence
  snapshot(): void;              // stash optimistic state
  restore(): void;               // roll back to last snapshot

  getSource(): RecordSource;
}
```

### Typical lifecycle

1. `network` delivers a response.
2. Relay writes it into a `RecordSource`.
3. `store.publish(recordSource)` merges it into the live source.
4. `store.notify()` walks subscribers whose snapshots changed and calls them.
5. `store.retain(operation)` keeps the data alive; disposing the returned `Disposable` releases it to the GC buffer.

### `publish()` and `notify()`

- `publish(source)` merges `source` into the store. It does not call subscribers.
- `notify()` calls the subscribers whose results changed since the last `notify()`. It returns the affected `RequestDescriptor`s.
- Call `publish()` several times, then `notify()` once, to deliver many payloads in one subscriber pass.
- Merge rules of `publish()`: records that exist only in the source are added; records that exist in both are merged field by field; records that are `null` in the source are deleted; records with the special sentinel value are removed (this undoes an optimistic record).
- `notify()` checks each subscription in 3 steps. First, it compares the changed record IDs with the IDs in the subscription's last `Snapshot`; no overlap skips the subscription. Second, it re-reads the overlapping subscriptions and compares the new result with the old one. Third, it calls the callback only when the result changed.

### Availability and invalidation

`environment.check(operation)` returns an object:

```ts
type OperationAvailability =
  | {status: 'available'; fetchTime: number | null}
  | {status: 'stale'}
  | {status: 'missing'};

if (environment.check(operation).status === 'stale') { /* refetch */ }
```

The docs write `environment.check(query) === 'stale'`. The source returns the object above, so compare `.status`.

An operation is `stale` when any of these holds:

- `store.invalidateStore()` ran after the operation was last written.
- `record.invalidateRecord()` ran on a record that the operation reaches, after the operation was last written.
- The operation's fetch time is older than the Store option `queryCacheExpirationTime`.

An operation with status `stale` or `missing` makes `fetchQuery` with `fetchPolicy: 'store-or-network'` issue a network request. Invalidation state API on the Store: `lookupInvalidationState(dataIDs)`, `checkInvalidationState(previous)` (returns `true` when the state changed), and `subscribeToInvalidationState(state, callback)`.

### Manual read + subscribe

```ts
import {createOperationDescriptor, getRequest} from 'relay-runtime';

const request = getRequest(MyQuery);
const operation = createOperationDescriptor(request, {id: '42'});
const retain = environment.retain(operation);

const snapshot = environment.lookup(operation.fragment);
console.log(snapshot.data);

const sub = environment.subscribe(snapshot, (next) => {
  console.log('updated', next.data);
});

// later
sub.dispose();
retain.dispose();
```

### Pause GC during batch writes

```ts
const hold = environment.getStore().holdGC();
try {
  for (const op of many) environment.commitPayload(op, data[op.name]);
} finally {
  hold.dispose(); // GC resumes
}
```

### Optimistic snapshot / restore

`snapshot()` captures the pre-optimistic store state; `restore()` rolls back. You rarely call these directly — `commitMutation` wraps them around `optimisticUpdater` / `optimisticResponse`.

## 3. RecordSource and proxies

`RecordSource` is the normalized record map: `DataID -> Record`. Two constructors:

```ts
new RecordSource();                 // empty
new RecordSource(serialized);       // rehydrate from `source.toJSON()`
```

Inside updater functions you never touch `RecordSource` directly; you receive a proxy.

### `RecordSourceProxy`

Low-level store mutation API passed to `commitLocalUpdate` and mutation `updater`s.

```ts
interface RecordSourceProxy {
  create(dataID: string, typeName: string): RecordProxy;
  delete(dataID: string): void;
  get<T>(dataID: string): RecordProxy<T> | null | undefined;
  getRoot(): RecordProxy;
  invalidateStore(): void;

  // Typed imperative updates (requires @updatable fragments/queries)
  readUpdatableFragment(fragment, fragmentRef): UpdatableData;
  readUpdatableQuery(query, variables): UpdatableData;
}
```

**Safety.** `RecordSourceProxy` exposes low-level APIs that TypeScript and Flow do not check against the schema. If the use case allows it, prefer `@updatable` fragments and queries (typed updaters), optimistic updates, or Relay Resolvers.

Behavior of `delete(dataID)`: edges that point to the deleted record read as `undefined`, even when the field type is non-null. Under `@throwOnFieldError`, the read throws. `invalidateStore()` marks all data written before the call as stale for `environment.check()` (see "Availability and invalidation"). `record.invalidateRecord()` does the same for the queries that reach that record.

### `RecordSourceSelectorProxy`

Extends `RecordSourceProxy` with selector-scoped helpers. Passed to mutation/subscription `updater`s because Relay knows which root fields the operation wrote.

```ts
interface RecordSourceSelectorProxy extends RecordSourceProxy {
  getRootField(fieldName: string): RecordProxy | null;
  getPluralRootField(fieldName: string): Array<RecordProxy | null> | null;
}
```

### `RecordProxy`

```ts
interface RecordProxy<T = {}> {
  getDataID(): string;
  getType(): string;

  getValue(name: string, args?: Variables): mixed;
  setValue(value: mixed, name: string, args?: Variables): RecordProxy<T>;

  getLinkedRecord(name: string, args?: Variables): RecordProxy | null;
  setLinkedRecord(record: RecordProxy, name: string, args?: Variables): RecordProxy<T>;
  getOrCreateLinkedRecord(name: string, typeName: string, args?: Variables): RecordProxy;

  getLinkedRecords(name: string, args?: Variables): Array<RecordProxy | null> | null;
  setLinkedRecords(records: Array<RecordProxy | null>, name: string, args?: Variables): RecordProxy<T>;

  copyFieldsFrom(source: RecordProxy): void;
  invalidateRecord(): void;
}
```

Field arguments must exactly match the arguments the query used — `friends(first: 10)` is a different storage key from `friends(first: 20)`.

## 4. ConnectionHandler

Helpers for mutating `@connection` edges consistently with Relay's pagination storage.

```ts
import {ConnectionHandler} from 'relay-runtime';

ConnectionHandler.getConnection(parent, connectionKey, filters?): RecordProxy | null;
ConnectionHandler.createEdge(store, connection, node, edgeType): RecordProxy;
ConnectionHandler.insertEdgeBefore(connection, newEdge, beforeCursor?): void;
ConnectionHandler.insertEdgeAfter(connection, newEdge, afterCursor?): void;
ConnectionHandler.deleteNode(connection, nodeID): void;
```

Example updater appending a comment:

```ts
function commentUpdater(store: RecordSourceSelectorProxy) {
  const newComment = store.getRootField('commentCreate')?.getLinkedRecord('comment');
  const feedback = store.get(feedbackID);
  if (!newComment || !feedback) return;

  const conn = ConnectionHandler.getConnection(
    feedback,
    'FeedbackCommentsQuery_comments',
  );
  if (!conn) return;

  const edge = ConnectionHandler.createEdge(store, conn, newComment, 'CommentEdge');
  ConnectionHandler.insertEdgeAfter(conn, edge);
}
```

## 5. fetchQuery

Imperative query execution. Returns an `Observable` — unlike `useLazyLoadQuery`, it does **not** retain the data. Retention is the caller's responsibility.

```ts
import {fetchQuery, graphql} from 'react-relay';

fetchQuery<AppQuery>(
  environment,
  graphql`
    query AppQuery($id: ID!) { user(id: $id) { id name } }
  `,
  {id: '4'},
  {networkCacheConfig: {force: true}},
).subscribe({
  start:    ()     => {},
  next:     (data) => console.log(data),
  error:    (err)  => console.error(err),
  complete: ()     => {},
});
```

### Signature

```ts
fetchQuery<TQuery>(
  environment: IEnvironment,
  query: GraphQLTaggedNode,
  variables: Variables,
  options?: {
    networkCacheConfig?: {force?: boolean; poll?: number; metadata?: object};
    fetchPolicy?: 'store-or-network' | 'network-only';
  },
): Observable<TQuery['response']>;
```

### Behavior

Source: `query/fetchQuery.js`, `query/fetchQueryInternal.js`; docs `api-reference/relay-runtime/fetch-query`.

- The request starts when you call `subscribe` or `toPromise`.
- Relay shares one network request between identical in-flight requests (same query and variables) that `fetchQuery` started.
- `fetchPolicy` is `'network-only'` by default. `'store-or-network'` reads the store when `environment.check(operation).status` is `'available'` and fetches otherwise. `'store-only'` and `'store-and-network'` are not supported. The v20 docs omit `fetchPolicy`; the v20 source supports both values.
- `networkCacheConfig.force` is `true` by default.
- The observer accepts `start(subscription)`, `next(data)`, `error(err)`, `complete()`, and `unsubscribe(subscription)`. `data` is a snapshot that Relay reads from the store when a payload arrives. The subscription covers the fetch only, not later store changes.
- `subscription.unsubscribe()` cancels the request while it is in flight.
- `fetchQuery` writes the response to the store and notifies subscribed components. It never retains the data, so garbage collection can remove it at any time after the request. Hold the data with `environment.retain(operation)`. A component that reads the result with `useLazyLoadQuery(..., {fetchPolicy: 'store-only'})` sends no request and depends on that retained data.

### `.toPromise()`

```ts
const data = await fetchQuery(env, Query, vars).toPromise();
```

Discouraged when the operation uses `@defer`, `@stream`, or `@module` — the promise resolves on the first payload and later chunks are lost.

The promise rejects when the request fails. You cannot cancel it. The docs advise against `toPromise()` in general.

### Retain across a render

`fetchQuery` writes to the store and does not retain the data. To keep data alive:

```ts
const operation = createOperationDescriptor(getRequest(Query), vars);
const disposable = environment.retain(operation);
fetchQuery(environment, Query, vars).subscribe({
  complete: () => {/* disposable.dispose() later */},
});
```

## 6. commitMutation

```ts
import {commitMutation, graphql} from 'react-relay';

const disposable = commitMutation<LikeMutation>(environment, {
  mutation: graphql`
    mutation LikeMutation($input: LikeInput!) {
      feedbackLike(input: $input) {
        feedback { id likeCount viewerDoesLike }
      }
    }
  `,
  variables: {input: {id: feedbackID}},
  optimisticResponse: {
    feedbackLike: {
      feedback: {id: feedbackID, likeCount: current + 1, viewerDoesLike: true},
    },
  },
  optimisticUpdater: (store) => {
    const fb = store.get(feedbackID);
    fb?.setValue(true, 'viewerDoesLike');
  },
  updater: (store, data) => {
    // Server response landed; coalesce with connection/cache updates.
  },
  onCompleted: (response, errors) => {
    if (errors) console.warn(errors);
  },
  onError: (err) => console.error(err),
  onUnsubscribe: () => {},
  cacheConfig: {force: true},
});

// Stop the request and the optimistic update. Callbacks stop after dispose.
// Before the request completes only; the network request is not guaranteed to cancel:
disposable.dispose();
```

### Config reference

| Field | Type | Notes |
| --- | --- | --- |
| `mutation` | `GraphQLTaggedNode` | The compiled `graphql` mutation. |
| `variables` | `Variables` | Matches operation variables. |
| `optimisticResponse` | raw server-shape object | Applied before the request returns; type matches `TMutation['rawResponse']`. Add `@raw_response_type` to the mutation to get the generated type. |
| `optimisticUpdater` | `(store: RecordSourceSelectorProxy) => void` | Runs before the network response. Complements `optimisticResponse` for connection / handle updates. |
| `updater` | `(store, data) => void` | Runs after the server response is normalized. Use for connection mutations (append/delete edges, cache invalidation). |
| `onCompleted` | `(response, errors?) => void` | Called after all updaters apply. |
| `onError` | `(error: Error) => void` | Network or GraphQL error. |
| `onUnsubscribe` | `() => void` | Called if the returned `Disposable` is disposed. |
| `cacheConfig` | `{force?, poll?, metadata?, transactionId?}` | Forwarded to the network layer. |
| `uploadables` | `{[key: string]: File \| Blob}` | Used by multipart file uploads. |
| `configs` | `DeclarativeMutationConfig[]` | Declarative range / node deletion directives (`RANGE_ADD`, `RANGE_DELETE`, `NODE_DELETE`). |

### Disposable semantics

Source: `mutations/commitMutation.js`; docs `api-reference/relay-runtime/commit-mutation`.

- `dispose()` before the request completes reverts the optimistic updates, prevents `onCompleted` and `onError`, and calls `onUnsubscribe`. It does not necessarily cancel the network request.
- `dispose()` after the request completes does nothing.
- `onCompleted(response, errors)` receives the mutation fragment as Relay reads it from the store after the updaters and the declarative directives (`@deleteRecord`, `@appendEdge`) ran. Data inside unmasked fragments is absent. Deleted records can be `null`. `errors` is `null` when no payload carried errors.
- `onNext()` (config key, no arguments) runs for each payload.

### Updater execution

Source: docs `guided-tour/updating-data/graphql-mutations`, `imperatively-modifying-store-data`.

1. Relay writes `optimisticResponse` to the store, then applies the declarative directives to the optimistic response, then runs `optimisticUpdater`.
2. On success, Relay rolls back the optimistic changes, writes the server response, applies the directives to the response, runs `updater` (the payload is a root field of the store proxy), then calls `onCompleted`.
3. On failure, Relay rolls back the optimistic changes and calls `onError`.

Rules for updater code:

- `updater` and `optimisticUpdater` can run 2 or more times for one mutation. Write them as idempotent functions of the store.
- `onCompleted` runs once. Put side effects there.
- When another write changes the store while the mutation is in flight, Relay reverts the optimistic update, applies the other write, and applies the optimistic update again.
- When 2 optimistic responses change the same value and the first rolls back, the second stays applied and Relay does not recompute it. A like count raised by 1 twice stays at +2.

### Declarative `configs`

```ts
configs: [
  {
    type: 'RANGE_ADD',
    parentID: feedbackID,
    connectionInfo: [{key: 'FeedbackComments_comments', rangeBehavior: 'append'}],
    edgeName: 'feedbackCommentEdge',
  },
  {type: 'NODE_DELETE', deletedIDFieldName: 'deletedCommentId'},
];
```

## 7. requestSubscription

```ts
import {requestSubscription, graphql} from 'react-relay';
import type {Disposable} from 'relay-runtime';

const disposable: Disposable = requestSubscription<UserSubscription>(environment, {
  subscription: graphql`
    subscription UserSubscription($input: InputData!) {
      userChanged(input: $input) { id name }
    }
  `,
  variables: {input: {userId: '4'}},
  onNext: (payload) => { /* normalized, also written to store */ },
  onError: (err) => console.error(err),
  onCompleted: () => {},
  updater: (store, data) => {},
  cacheConfig: {metadata: {tenant: 'acme'}},
});

// later
disposable.dispose();
```

Network subscriptions require passing a `subscribe` function to `Network.create(fetch, subscribe)` — see the network skill file. `updater` fires on every payload.

### Config reference

Source: `subscription/requestSubscription.js`; docs `api-reference/relay-runtime/request-subscription`.

| Field | Type | Notes |
| --- | --- | --- |
| `subscription` | `GraphQLTaggedNode` | Required. Must be a `subscription` operation; Relay throws for another kind. |
| `variables` | `Variables` | Required. |
| `onNext` | `(data) => void` | Receives the data that Relay reads from the store after it normalizes the payload. |
| `onError` | `(error: Error) => void` | Called when the subscription fails. |
| `onCompleted` | `() => void` | Called when the subscription observable completes. The docs say "when the subscription is established"; the source passes it as the `complete` handler, so it follows the source. |
| `updater` | `(store, data) => void` | Store updater for each payload. |
| `configs` | `DeclarativeMutationConfig[]` | Same declarative configs as `commitMutation`. Use only one of `configs` and `updater`; Relay logs a warning when both are present. |
| `cacheConfig` | `{force?, poll?, metadata?, transactionId?, liveConfigId?}` | Forwarded to the network layer. |

`disposable.dispose()` unsubscribes and ends the subscription.

## 8. commitLocalUpdate

Apply a purely-client-side mutation to the store. No network request, no optimistic lifecycle. Useful for UI state encoded as client fields, undo stacks, form drafts, derived client records.

```ts
import {commitLocalUpdate} from 'react-relay';

commitLocalUpdate(environment, (store) => {
  const root = store.getRoot();
  let session = root.getLinkedRecord('session');
  if (!session) {
    session = store.create('client:session', 'Session');
    root.setLinkedRecord(session, 'session');
  }
  session.setValue(true, 'isSidebarOpen');
});
```

Signature:

```ts
commitLocalUpdate(
  environment: IEnvironment,
  updater: (store: RecordSourceProxy) => void,
): void;
```

The `updater` receives only `store`. It gets no second `data` argument because no network response exists. Subscribed components re-render after the update. `commitLocalUpdate` works on client-only data and on server data. It calls `environment.commitUpdate(updater)`, which runs the update through the publish queue.

`environment.commitPayload(operation, payload)` writes a query payload to the store as if the server had returned it. Create `operation` with `createOperationDescriptor(request, variables)`. Type the payload with the `FooQueryRawResponse` type, which the compiler generates for queries that carry `@raw_response_type`. Subscribed components re-render after the write.

For typed imperative edits, pair with `@updatable`:

```graphql
fragment SessionFragment on Session @updatable {
  isSidebarOpen
}
```

```ts
commitLocalUpdate(environment, (store) => {
  const {updatableData} = store.readUpdatableFragment(SessionFragment, ref);
  updatableData.isSidebarOpen = true;
});
```

## 9. RelayEnvironmentProvider

Publishes an `Environment` via React context so hooks can find it.

```tsx
import {RelayEnvironmentProvider} from 'react-relay';
import {environment} from './relay/environment';

export function Root() {
  return (
    <RelayEnvironmentProvider environment={environment}>
      <App />
    </RelayEnvironmentProvider>
  );
}
```

Props:

| Prop | Type | Notes |
| --- | --- | --- |
| `environment` | `IEnvironment` | Required. Swapping the instance re-renders all consumers — typically stable for the app lifetime. |
| `children` | `ReactNode` | |

Multiple providers can be nested (e.g. per-tenant environment) — the nearest ancestor wins.

## 10. useRelayEnvironment

```ts
import {useRelayEnvironment} from 'react-relay';

function PrefetchButton({id}: {id: string}) {
  const env = useRelayEnvironment();
  return (
    <button onClick={() => fetchQuery(env, UserQuery, {id}).subscribe({})}>
      Prefetch
    </button>
  );
}
```

Returns the nearest `IEnvironment`. Throws if no provider is above the caller. Safe to call conditionally **within** a component (it's a context read), but follow the normal hooks rules.

## 11. When to use imperative APIs vs hooks

Prefer hooks for anything rendered. Reach for the runtime APIs only when:

- **Prefetching on intent** — `onMouseEnter`, router `preload`, service worker — before a component mounts.
- **Outside React** — Redux middleware, state machines, workers, CLI/SSR scripts.
- **Side-effect orchestration** — fire-and-forget telemetry writes, cache warming, background sync.
- **Store manipulation** — client state via `commitLocalUpdate`, updater functions inside mutations/subscriptions.
- **SSR** — construct a per-request `Environment`, fetch, serialize `store.getSource().toJSON()`.
- **Testing** — `createMockEnvironment()` plus direct `commitPayload` / `mock.resolveMostRecentOperation`.

If a component needs the data, still render via `usePreloadedQuery` / `useFragment`; imperative fetches should feed the same store the hooks read.

## 12. Hook vs imperative equivalent

| Hook (React) | Imperative equivalent (runtime) |
| --- | --- |
| `useLazyLoadQuery(query, vars)` | `fetchQuery(env, query, vars).subscribe(...)` + `environment.retain(op)` |
| `usePreloadedQuery(query, ref)` | `loadQuery(env, query, vars)` — produces the ref imperatively |
| `useQueryLoader(query)` | `loadQuery` / manual `Disposable` tracking |
| `useFragment(fragment, ref)` | `environment.lookup(selector)` + `environment.subscribe(snapshot, cb)` |
| `usePaginationFragment` | `ConnectionHandler` edits + manual `fetchQuery` with pagination vars |
| `useMutation(mutation)` | `commitMutation(env, config)` |
| `useSubscription(config)` | `requestSubscription(env, config)` |
| `useRelayEnvironment()` | Pass `environment` explicitly |
| `commitLocalUpdate` (no hook) | `commitLocalUpdate(env, updater)` |
| `useClientQuery` | `fetchQuery` against a query containing only client fields |
| `useRefetchableFragment` | `fetchQuery` with refetch variables + `ConnectionHandler` reconciliation |

## 13. Field logger events

Source: docs `api-reference/relay-runtime/field-logger`; types in `store/RelayStoreTypes.js` (same in v20.1.1 and v21.0.1).

`relayFieldLogger` receives one event each time Relay handles a field-level error. Every event has `owner` (the fragment, query, or mutation name), `fieldPath` (`.`-separated path from the owner to the field), and `uiContext`. Events that can throw also carry `handled`; throw your own error only when `handled` is `false`. A `@catch` directive or a nullable resolver sets `handled` to `true`.

| `kind` | Raised when | Extra fields |
| --- | --- | --- |
| `missing_expected_data.log` | Data that the operation requested is absent from the store. The field reads as `undefined`. | none |
| `missing_expected_data.throw` | Same, inside a `@throwOnFieldError` operation. Relay throws after the logger returns. | `handled` |
| `missing_required_field.log` | A `@required(action: LOG)` field is `null` or missing. | none |
| `missing_required_field.throw` | A `@required(action: THROW)` field is `null` or missing. | `handled` |
| `relay_resolver.error` | A Relay Resolver threw. Relay coerces the value to `null`. | `error`, `shouldThrow`, `handled` |
| `relay_field_payload.error` | The GraphQL response marked the field as an error. | `error`, `shouldThrow`, `handled` |

For `missing_expected_data`, `fieldPath` can end in `<record>` (an edge points to an ID that the store lacks) or `<abstract-type-hint>` (the compiler's virtual type-check field is missing).

The default logger does nothing, except in development: it throws when it receives `missing_required_field.log`, because `@required(action: LOG)` needs a configured `relayFieldLogger`.

## 14. `readInlineData`

`readInlineData(fragment, ref)` reads a fragment that carries `@inline` from a fragment reference. It reads no store and creates no subscription. Use it in plain functions that run outside render. It returns `ref` unchanged when `ref` is `null` or `undefined`. It throws when the parent fragment did not spread the `@inline` fragment.

```ts
import {graphql, readInlineData} from 'relay-runtime';

function logUser(userRef: logUser_user$key) {
  const user = readInlineData(
    graphql`fragment logUser_user on User @inline { id name }`,
    userRef,
  );
  analytics.log(user.id, user.name);
}
```

Source: `store/readInlineData.js`. Details of `@inline`: see `directives.md`.

## 15. `observeFragment` and `waitForFragmentData` (experimental)

Both functions read a fragment outside React. The docs mark both as experimental. They exist in v20.1.x and in v21.0.1 (`store/observeFragmentExperimental.js`, `store/waitForFragmentExperimental.js`; the v20 and v21 docs describe them in the same words). Import them from `relay-runtime/experimental`. They are not exports of the `relay-runtime` entry point.

Both take `environment` as the first argument. The source signature is `(environment, fragment, fragmentRef)`. The docs examples omit `environment` and read `result.kind`. The source reads `state`, so write `result.state`.

```ts
import {observeFragment, waitForFragmentData} from 'relay-runtime/experimental';

const subscription = observeFragment(environment, TitleFragment, userRef).subscribe({
  next: (result) => {
    if (result.state === 'ok') document.title = result.value.name;
    else if (result.state === 'error') console.error(result.error);
  },
});
subscription.unsubscribe();

const age = (await waitForFragmentData(environment, AgeFragment, userRef)).age;
```

| Function | Returns | States and behavior |
| --- | --- | --- |
| `observeFragment` | `Observable<FragmentState<T>>` | `{state: 'ok', value}`: data present. `{state: 'error', error}`: network error, `@throwOnFieldError`, or `@required(action: THROW)`. `{state: 'loading'}`: the parent request or the current `@defer` payload is in flight, or a `@live` resolver is suspended. Emits again on each store change. |
| `waitForFragmentData` | `Promise<T>` | Waits for network data and for `@live` resolvers to leave the suspended state. Resolves on the first `ok` state. Rejects on the first `error` state. Unsubscribes afterwards. |

Both accept an array of fragment references for a plural fragment. With a plural fragment, `observeFragment` can call `next` several times, synchronously, for one store update that touches several items. Debounce for one tick and use the last value.

Known limits: a fragment with client edges throws `Client edges aren't supported yet.` in v20; v21 accepts them only when the fragment uses exec-time resolvers. The type declarations note that the functions do not fully handle Relay Resolvers.
