# Caching & Data Freshness

Relay's normalized store is the heart of its caching story. Every field fetched by any query is flattened into a record graph keyed by global IDs, so data fetched by one query can often be served from the cache when a sibling query asks for an overlapping shape. This reference covers what lives in the cache, how long it stays there, how to control freshness, and how to render partially-cached screens without flash-of-loading states.

All examples use hooks (`useLazyLoadQuery`, `useQueryLoader`, `usePreloadedQuery`, `useFragment`, `useSubscribeToInvalidationState`).

---

## 1. The Mental Model

A Relay `Environment` owns a `Store`, which owns a `RecordSource` (a map of `dataID -> Record`). When a query response arrives, Relay:

1. Normalizes the response into flat records keyed by `id` (or a synthetic ID for unidentified objects).
2. Writes records into the `RecordSource`.
3. Notifies subscribed components of affected IDs so they re-read from the store.

Because data is normalized, a `user(id: 4) { name }` write is visible to any later query that touches user `4`, regardless of how it reached that node (via `node(id: 4)`, a connection edge, a fragment spread, etc).

Three questions drive everything in this document:

- **Presence** — do we have any data for this query shape in the store?
- **Staleness** — is that data still considered fresh?
- **Retention** — who is keeping this data alive, and when can GC delete it?

---

## 2. Fetch Policies

Fetch policies are the primary knob for trading latency for freshness. They are accepted by `useLazyLoadQuery`, `loadQuery` (via `useQueryLoader`), and `refetch`.

### 2.1 The Four Policies

| Policy | Use cache? | Send network request? |
|---|---|---|
| `store-or-network` *(default)* | Yes | Only if data missing or stale |
| `store-and-network` | Yes | Always |
| `network-only` | No | Always |
| `store-only` | Yes | Never |

#### `store-or-network` (default)

Reuse cached data if the query is fully available and fresh; otherwise fetch from the network. This is the right choice for ~80% of queries — page transitions, repeat visits, detail views opened from a list.

```tsx
import { useLazyLoadQuery, graphql } from 'react-relay';

function ProfileScreen({ userId }: { userId: string }) {
  const data = useLazyLoadQuery<ProfileQuery>(
    graphql`
      query ProfileQuery($id: ID!) {
        user(id: $id) {
          name
          avatarUrl
        }
      }
    `,
    { id: userId },
    { fetchPolicy: 'store-or-network' }, // default, can omit
  );
  return <Profile user={data.user} />;
}
```

#### `store-and-network`

Render cached data immediately, then revalidate from the network. The component shows something instantly, and re-renders when the fresh response lands. Good for dashboards, feeds, and anything where "stale while revalidate" is the desired UX.

```tsx
const data = useLazyLoadQuery<FeedQuery>(
  FeedQueryNode,
  { first: 20 },
  { fetchPolicy: 'store-and-network' },
);
```

#### `network-only`

Ignore the cache entirely. Use for actions where a stale answer is worse than a spinner: post-mutation confirmations, payment status, anything behind a "Refresh" button the user explicitly pressed.

```tsx
const [queryRef, loadQuery] = useQueryLoader<OrderStatusQuery>(OrderStatusQueryNode);

function refresh() {
  loadQuery({ orderId }, { fetchPolicy: 'network-only' });
}
```

Note: the response *is* written to the store after arrival — subsequent `store-or-network` reads will see it. "Network-only" only bypasses the cache on *read*.

#### `store-only`

Never hit the network. Caller guarantees data is already present (e.g. written by a mutation optimistic updater, seeded by SSR, or prefetched by another route). Also useful for reading purely client-only `@client`/local schema fields.

```tsx
const data = useLazyLoadQuery<PreloadedQuery>(
  PreloadedQueryNode,
  vars,
  { fetchPolicy: 'store-only' },
);
```

### 2.2 Decision Tree

```
Need guaranteed fresh data?         -> network-only
Data pre-seeded / client-only?      -> store-only
UX tolerates brief stale flash
while revalidating?                 -> store-and-network
Otherwise (default)                 -> store-or-network
```

---

## 3. Presence of Data (Cache Hits)

A query is considered *present* when every selection in the operation can be satisfied from the store. This is evaluated per-field, walking the normalized graph starting from the query root.

### 3.1 What Counts as "Present"

Data for a query is present after the query has been fetched *and* while at least one component is mounted that retains it (or it is still inside the GC release buffer). Without a retainer, GC may delete the records at any time, causing the next read to be a miss.

Rules of thumb:

- If the query was never fetched, it is a miss.
- If some fields are missing (e.g. a newly-added selection), it is a miss for the operation as a whole.
- Fields reached only through a child fragment spread do *not* count against the outer query's presence check — fragment components have their own suspense boundary (see §6).

### 3.2 Suspense on Miss

`useLazyLoadQuery` and `usePreloadedQuery` throw a promise (suspend) when data is missing and a network request is in-flight. Wrap the rendering tree in `<Suspense>`:

```tsx
<Suspense fallback={<Spinner />}>
  <ProfileScreen userId={id} />
</Suspense>
```

With `store-or-network`, a cache hit returns synchronously without suspending — enabling instant navigation.

---

## 4. Query Retention & Garbage Collection

### 4.1 What Retention Means

"Retaining" a query tells Relay: *do not GC the records reachable from this query's root selection*. As long as at least one retainer holds a given operation (query + variables), its data stays in the store.

When all retainers release, the query enters a **release buffer**. If it is not re-retained within the buffer window, GC eventually evicts its exclusively-owned records.

### 4.2 Automatic Retention via Hooks

Under the hood, the hooks retain their queries for you:

| Hook | Retained while |
|---|---|
| `useLazyLoadQuery(query, vars, options)` | Component is mounted |
| `useQueryLoader(query)` + `loadQuery()` | `queryRef` is held (retention disposed when `disposeQuery()` is called or the loader is unmounted) |
| `usePreloadedQuery(query, queryRef)` | Component is mounted *and* the backing `queryRef` is alive |

The `useQueryLoader` pattern is especially powerful for navigation: you can load a query before the destination component is rendered, and the `queryRef` keeps the data retained through the transition.

```tsx
function App() {
  const [queryRef, loadQuery, disposeQuery] =
    useQueryLoader<ProfileQuery>(ProfileQueryNode);

  return (
    <>
      <button onClick={() => loadQuery({ id: '4' })}>
        Open profile
      </button>
      <Suspense fallback={<Spinner />}>
        {queryRef && <Profile queryRef={queryRef} />}
      </Suspense>
      <button onClick={disposeQuery}>Close</button>
    </>
  );
}

function Profile({ queryRef }: { queryRef: PreloadedQuery<ProfileQuery> }) {
  const data = usePreloadedQuery(ProfileQueryNode, queryRef);
  return <h1>{data.user?.name}</h1>;
}
```

### 4.3 Manual Retention with `environment.retain()`

Outside React (routers, infra code, prefetchers), retain a query descriptor directly:

```ts
import {
  createOperationDescriptor,
  getRequest,
  graphql,
} from 'relay-runtime';

const query = graphql`
  query PrefetchQuery($id: ID!) {
    user(id: $id) { name }
  }
`;

const request = getRequest(query);
const descriptor = createOperationDescriptor(request, { id: '4' });

const disposable = environment.retain(descriptor);
// ... later
disposable.dispose();
```

`retain()` is idempotent per caller — each call returns its own disposable, and the query stays alive until every disposable is disposed. This is a low-level API; application code should almost always rely on hooks.

### 4.4 The Release Buffer (`gcReleaseBufferSize`)

When a retainer releases, the operation is held in a FIFO release buffer. If the user re-navigates to the same screen before the buffer evicts it, no refetch is needed — the data is still there.

```ts
import { Environment, Network, RecordSource, Store } from 'relay-runtime';

const store = new Store(new RecordSource(), {
  gcReleaseBufferSize: 10, // default 10
});
```

Tune based on navigation depth: SPAs with deep back/forward flows benefit from a larger buffer; memory-constrained contexts (mobile web) may want a smaller one.

### 4.5 GC Scheduler

GC is triggered when records become orphaned. By default, it runs synchronously on release. Supply a custom scheduler to defer work to idle time:

```ts
const store = new Store(new RecordSource(), {
  gcScheduler: (run) => {
    // e.g. requestIdleCallback, or delay until transitions settle
    requestIdleCallback(run);
  },
});
```

Use this if GC causes noticeable jank during rapid navigation.

### 4.6 Query Cache Expiration (Age-Based Staleness)

`queryCacheExpirationTime` (milliseconds) marks any query older than that threshold as stale. Stale queries trigger a network request on the next `store-or-network` read, even when all records are present.

```ts
const store = new Store(new RecordSource(), {
  queryCacheExpirationTime: 5 * 60 * 1000, // 5 minutes
});
```

This is the primary age-based TTL knob. Pair with `store-or-network` for "fresh-for-N-minutes, then refetch on next view" behavior.

---

## 5. Staleness & Invalidation

Relay does not auto-expire records based on age (unless you configure `queryCacheExpirationTime`). Staleness is almost always explicit: something marks a record or the whole store stale, and the next read that intersects re-fetches.

### 5.1 Global: `invalidateStore()`

Inside an updater, invalidate every record at once. The next `store-or-network` evaluation of any query will issue a network request.

```ts
import { commitLocalUpdate } from 'react-relay';

commitLocalUpdate(environment, (store) => {
  store.invalidateStore();
});
```

Use after a session change (login/logout), a major mutation with broad side effects, or a "global refresh" action.

### 5.2 Record-Level: `invalidateRecord()`

Much more surgical — only queries that reference the invalidated record(s) are considered stale.

```ts
import { commitLocalUpdate } from 'react-relay';

commitLocalUpdate(environment, (store) => {
  const user = store.get(userId);
  user?.invalidateRecord();
});
```

### 5.3 Invalidating from Mutations

Use the mutation's `updater`/`optimisticUpdater` to invalidate server-side side-effect targets:

```tsx
const [commit] = useMutation<DeletePostMutation>(DeletePostMutationNode);

commit({
  variables: { postId },
  updater: (store) => {
    store.get(postId)?.invalidateRecord();
    store.get(authorId)?.invalidateRecord(); // author.postCount is now stale
  },
});
```

### 5.4 Reacting: `useSubscribeToInvalidationState`

Invalidation alone only marks data stale — it does not trigger a refetch on *already-mounted* components. If the invalidated data is visible *right now*, subscribe and trigger a refetch:

```tsx
import {
  useSubscribeToInvalidationState,
  useRefetchableFragment,
} from 'react-relay';

function Profile({ userRef }: { userRef: Profile_user$key }) {
  const [data, refetch] = useRefetchableFragment<
    ProfileRefetchQuery,
    Profile_user$key
  >(ProfileFragmentNode, userRef);

  useSubscribeToInvalidationState([data.id], () => {
    refetch({}, { fetchPolicy: 'network-only' });
  });

  return <h1>{data.name}</h1>;
}
```

Without this subscription, the mounted component continues to display the stale data until it unmounts/remounts, at which point the next read sees the stale flag and refetches.

### 5.5 How `useLazyLoadQuery` Handles Staleness

On each render, `useLazyLoadQuery` checks whether the query is present *and* non-stale:

- Present + fresh → synchronous cache hit, no network request.
- Present + stale (invalidated or past `queryCacheExpirationTime`) → still returns cached data for `store-or-network`, *plus* triggers a network request; component re-renders when the response arrives.
- Missing → suspends, fetches.

---

## 6. Rendering Partially Cached Data

Fragment spreads do *not* count against the outer query's presence check. This means the outer query can render synchronously from cache while a child fragment with missing fields suspends independently.

### 6.1 Example

```tsx
function HomeTab({ queryRef }: Props) {
  const data = usePreloadedQuery<HomeTabQuery>(
    graphql`
      query HomeTabQuery($id: ID!) {
        user(id: $id) {
          name
          ...UsernameComponent_user
        }
      }
    `,
    queryRef,
  );
  return (
    <>
      <h1>{data.user?.name}</h1>
      <Suspense fallback={<Spinner label="Loading username" />}>
        <UsernameComponent userRef={data.user} />
      </Suspense>
    </>
  );
}

function UsernameComponent({ userRef }: { userRef: UsernameComponent_user$key }) {
  const user = useFragment(
    graphql`
      fragment UsernameComponent_user on User {
        username
      }
    `,
    userRef,
  );
  return <span>@{user.username}</span>;
}
```

If `name` is cached but `username` is not, the header appears instantly; the username slot shows its own spinner and upgrades when the fragment's data arrives. Without the nested `<Suspense>`, the whole tree would suspend to the outer boundary.

**Rule**: wherever a fragment may be rendered with partial data, wrap it in a local `<Suspense>` with a per-section fallback.

---

## 7. Filling In Missing Data: `missingFieldHandlers`

Two queries can reference the same underlying record via different entry points:

```graphql
query A { user(id: 4) { name } }
query B { node(id: 4) { ... on User { name } } }
```

By default, Relay treats these as independent and won't recognize the overlap when query B runs after query A. `missingFieldHandlers` teach the runtime how to map one shape to another.

### 7.1 Configuration

```ts
import { Environment, Network, RecordSource, Store, ROOT_TYPE } from 'relay-runtime';

const missingFieldHandlers = [
  {
    kind: 'linked' as const,
    handle(field, record, argValues) {
      if (
        record?.getType() === ROOT_TYPE &&
        field.name === 'user' &&
        argValues.hasOwnProperty('id')
      ) {
        return argValues.id; // map Query.user(id) -> node with that ID
      }
      if (
        record?.getType() === ROOT_TYPE &&
        field.name === 'node' &&
        argValues.hasOwnProperty('id')
      ) {
        return argValues.id;
      }
    },
  },
];

const environment = new Environment({
  network: Network.create(fetchFn),
  store: new Store(new RecordSource()),
  missingFieldHandlers,
});
```

### 7.2 Handler Kinds

- `'scalar'` — returns a scalar value (number, string, boolean).
- `'linked'` — returns a `dataID` referencing another record in the store.
- `'pluralLinked'` — returns an array of `dataID`s.

During cache evaluation, when Relay encounters a missing field, it runs matching handlers before declaring the query incomplete. A handler that returns `undefined` is a no-op; a handler that returns a valid ID/value satisfies the miss and the query can be served from cache.

Common handlers to add: `node(id:)` → `id`, `user(id:)` → `id`, `viewer()` → a well-known viewer record ID.

---

## 8. Connections & Pagination

Relay stores connections as `Record` nodes keyed by the parent + `@connection` key + filter args. Pagination appends edges into that record. For caching purposes:

- A paginated connection is cached per unique `(parentId, connectionKey, filters)` tuple.
- Navigating away and back hits the cache if the same filters are in play.
- Cursor state lives inside the connection record (`pageInfo`), so resuming `loadNext()` just works.

Cache-aware pagination pattern:

```tsx
function Feed({ userRef }: Props) {
  const { data, loadNext, hasNext, isLoadingNext } = usePaginationFragment(
    graphql`
      fragment Feed_user on User
      @argumentDefinitions(count: { type: "Int", defaultValue: 10 },
                           cursor: { type: "String" })
      @refetchable(queryName: "FeedPaginationQuery") {
        posts(first: $count, after: $cursor)
          @connection(key: "Feed_posts") {
          edges { node { id ...PostRow_post } }
        }
      }
    `,
    userRef,
  );
  // ...
}
```

Invalidate a connection after a mutation that adds/removes edges:

```ts
updater: (store) => {
  const user = store.get(userId);
  const conn = user && ConnectionHandler.getConnection(user, 'Feed_posts');
  if (conn) {
    const edge = ConnectionHandler.createEdge(store, conn, newPost, 'PostEdge');
    ConnectionHandler.insertEdgeBefore(conn, edge);
  }
},
```

For cursor-based caches, prefer explicit edge insertion over `invalidateRecord` — the latter forces a full refetch that resets pagination state.

---

## 9. Record TTL / Age-Based Strategies

Relay has no built-in per-record TTL, but there are three idiomatic patterns:

### 9.1 Global TTL via `queryCacheExpirationTime`

Simple. Every query older than N ms is stale. Pair with `store-or-network`.

```ts
new Store(source, { queryCacheExpirationTime: 5 * 60 * 1000 });
```

### 9.2 Timer-Driven Invalidation

For specific records with known lifetimes (e.g. auth tokens, feature flags), schedule explicit invalidation:

```ts
setInterval(() => {
  commitLocalUpdate(environment, (store) => {
    store.get(featureFlagsId)?.invalidateRecord();
  });
}, 60 * 1000);
```

### 9.3 Event-Driven Invalidation

Invalidate from websocket/subscription messages that signal upstream change:

```ts
subscription.on('post:updated', ({ id }) => {
  commitLocalUpdate(environment, (store) => {
    store.get(id)?.invalidateRecord();
  });
});
```

Mounted readers of that record should use `useSubscribeToInvalidationState` to refetch proactively (§5.4).

---

## 10. Debugging the Cache

- **Relay DevTools** (browser extension): inspect the `RecordSource`, list retained operations, see invalidation state per record.
- **`environment.getStore().getSource().toJSON()`** dumps the full normalized record map — useful in tests or ad-hoc assertions.
- **`environment.check(operationDescriptor)`** returns `'available' | 'missing' | 'stale'` for a given query without triggering a fetch. Handy for writing custom routing pre-checks.

---

## 11. Fetch Policy Decision Table

| Scenario | Recommended policy | Why |
|---|---|---|
| Default page navigation | `store-or-network` | Instant if cached, fetch if not |
| Feed/dashboard with SWR desired | `store-and-network` | Show something immediately, revalidate |
| "Pull to refresh" / manual refresh button | `network-only` | User explicitly asked for fresh |
| Post-mutation confirmation screen | `network-only` | Avoid stale optimistic state |
| Route prefetched via `useQueryLoader` | `store-or-network` | Loader warms cache; consumer reuses |
| Client-only / `@client` field read | `store-only` | No server source of truth |
| Optimistic-only UI slice | `store-only` | Data is synthesized locally |
| Detail view opened from a list (both queries overlap) | `store-or-network` + `missingFieldHandlers` | Maximize cache hit via `node(id:)` mapping |
| Data known to expire on a schedule | `store-or-network` + `queryCacheExpirationTime` | Age-based auto-refetch |
| Stale-after-mutation, may or may not be visible | `invalidateRecord()` in updater | Next read refetches; visible views use `useSubscribeToInvalidationState` |

---

## 12. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Query refetches every render | No Suspense boundary, or component re-mounting | Wrap in stable `<Suspense>`; stabilize parent keys |
| Data gone after brief unmount/remount | Release buffer too small; GC ran | Increase `gcReleaseBufferSize`; consider `useQueryLoader` to hold retention |
| "Missing data" error despite recent fetch | Different query shape; no missing-field handler | Add `missingFieldHandlers` for `node`/`user`/`viewer` mappings |
| Stale data still visible after mutation | Invalidated but component already mounted | Add `useSubscribeToInvalidationState` and call `refetch` |
| Cache never clears on logout | No retainer, but records linger in release buffer | Call `store.invalidateStore()` inside `commitLocalUpdate`, or swap to a fresh `Environment` |
| `store-or-network` won't refetch fresh server data | Query is present and fresh per Relay | Use `store-and-network` or set `queryCacheExpirationTime` |
| `store-only` returns partial data and suspends forever | Required fields genuinely missing | Ensure prefetch wrote all selected fields; or switch to `store-or-network` |
| Fragment at leaf suspends the whole screen | Missing local `<Suspense>` boundary | Wrap the partially-cached fragment in its own `<Suspense>` |
| GC causes jank during rapid navigation | Synchronous default scheduler | Provide `gcScheduler: requestIdleCallback` |
| Pagination resets unexpectedly | `invalidateRecord` on a connection parent | Use explicit `ConnectionHandler` edge insertion instead |
| `useLazyLoadQuery` unretains too eagerly with StrictMode double-invoke | Mount/unmount/mount race outpaces release buffer | Prefer `useQueryLoader` + `usePreloadedQuery`; or increase `gcReleaseBufferSize` |
| Mounted list doesn't reflect a new record written via updater | Connection not updated | Insert edge via `ConnectionHandler.insertEdgeBefore/After` in the mutation updater |

---

## 13. Summary

- Default to `store-or-network`. Upgrade to `store-and-network` for SWR, `network-only` for forced freshness, `store-only` for local/prefetched data.
- Hooks (`useLazyLoadQuery`, `useQueryLoader`/`usePreloadedQuery`) retain queries automatically while mounted; the release buffer smooths navigation.
- Tune lifecycle via `gcReleaseBufferSize`, `gcScheduler`, and `queryCacheExpirationTime` on the `Store`.
- Mark data stale with `invalidateStore()` / `invalidateRecord()` inside `commitLocalUpdate` or mutation updaters. Use `useSubscribeToInvalidationState` to refetch visible stale data.
- Wrap every partially-cacheable fragment in its own `<Suspense>` to unlock partial rendering.
- Teach Relay about equivalent query shapes with `missingFieldHandlers` to maximize cache hits.
