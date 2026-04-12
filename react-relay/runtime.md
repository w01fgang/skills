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
| `store` | `Store` | Required. Holds normalized records and tracks subscribers. |
| `handlerProvider` | `(handle: string) => Handler` | Maps `@__clientField(handle: "...")` / connection handles to runtime handlers. Defaults to `RelayDefaultHandlerProvider`. |
| `operationLoader` | `{ get(ref): ?Node; load(ref): Promise<?Node> }` | Required if using `@module` / 3D. Resolves split operations lazily. |
| `missingFieldHandlers` | `MissingFieldHandler[]` | Lets Relay satisfy missing scalars / linked records from adjacent data (e.g. treat `node(id:$x)` as already cached if `User:$x` exists). |
| `isServer` | `boolean` | Disables client-only optimizations; set `true` during SSR. |
| `treatMissingFieldsAsNull` | `boolean` | If `true`, reads return `null` for missing fields instead of suspending / erroring. |
| `log` | `(event: LogEvent) => void` | Receives lifecycle events: `queryresource.fetch`, `network.start/next/complete/error`, `execute.start/next/error/complete`, `store.publish`, `store.gc`, etc. Use for metrics. |
| `requiredFieldLogger` | `(event) => void` | Receives `@required` violations without throwing. |
| `scheduler` | `TaskScheduler` | Custom scheduler for batching store notifications (e.g. `unstable_batchedUpdates`). |
| `getDataID` | `(fieldValue, typeName) => string` | Override Relay's default identity (default reads `id`). Useful for composite keys. |
| `UNSTABLE_defaultRenderPolicy` | `'partial' \| 'full'` | Toggles whether partial store data satisfies a read. |

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
  queryCacheExpirationTime: 5 * 60_1000, // ms before cached ops are invalidated
});
```

### Core methods

```ts
interface Store {
  // Retention & GC
  retain(operation: OperationDescriptor): Disposable;
  holdGC(): Disposable;          // pause garbage collection
  check(operation): OperationAvailability; // 'available' | 'stale' | 'missing'

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

### `.toPromise()`

```ts
const data = await fetchQuery(env, Query, vars).toPromise();
```

Discouraged when the operation uses `@defer`, `@stream`, or `@module` — the promise resolves on the first payload and later chunks are lost.

### Retain across a render

`fetchQuery` writes to the store but releases after the observable completes. To keep data alive:

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

// Cancel optimistic + suppress callbacks:
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
