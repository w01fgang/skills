# Caching & Data Freshness

Relay maintains a normalized data store, so components that observe the same data stay in sync even if they reach it by different queries. This reference covers what lives in the cache, how long it stays there, how to control freshness, and how to render partially cached screens.

---

## 1. The Mental Model

Three questions drive everything in this document:

- **Presence** — is the data for this query in the store?
- **Staleness** — is that data still considered fresh?
- **Retention** — who keeps this data alive, and when can garbage collection (GC) delete it?

---

## 2. Fetch Policies

Pass a `fetchPolicy` to the `loadQuery` function, which `useQueryLoader` provides:

```js
const React = require('React');
const {graphql} = require('react-relay');

function AppTabs() {
  const [
    queryRef,
    loadQuery,
  ] = useQueryLoader(HomeTabQuery);

  const onSelectHomeTab = () => {
    loadQuery({id: '4'}, {fetchPolicy: 'store-or-network'});
  }

  // ...
}
```

`useLazyLoadQuery` takes the `fetchPolicy` in its options argument:

```js
const React = require('React');

const {graphql, useLazyLoadQuery} = require('react-relay');

function App() {
  const data = useLazyLoadQuery(
    graphql`
      query AppQuery($id: ID!) {
        user(id: $id) {
          name
        }
      }
    `,
    {id: 4},
    {fetchPolicy: 'store-or-network'},
  );

 return <h1>{data.user?.name}</h1>;
}
```

The `fetchPolicy` determines:

- whether the query is fulfilled from the local cache, and
- whether a network request is made to fetch the query from the server, depending on the availability of the data for that query in the store.

The `refetch` function also takes a `fetchPolicy`. `fetchQuery` supports only `network-only` (the default) and `store-or-network`.

### The Four Policies

| Policy | Use cache? | Send network request? |
|---|---|---|
| `store-or-network` *(default)* | Yes | Only if data is missing or stale |
| `store-and-network` | Yes | Always |
| `network-only` | No | Always |
| `store-only` | Yes | Never |

- `store-or-network`: reuses locally cached data. Sends a network request only if any data for the query is missing or stale. If the query is fully cached, no network request is made.
- `store-and-network`: reuses locally cached data and always sends a network request, regardless of whether data was missing or stale in the store.
- `network-only`: does not reuse locally cached data and always sends a network request, ignoring any data that might be locally cached and whether it is missing or stale.
- `store-only`: only reuses locally cached data and never sends a network request. The caller fetches the query. This policy can also read and operate on data that is entirely local.

---

## 3. Presence of Data (Cache Hits)

Data in the Relay store for a given query is present after the query has been fetched for the first time, as long as that query is rendered on the screen. If data was never fetched for a query, it is missing from the store.

Relay runs *Garbage Collection* to delete data that no component in the app references. If GC deletes data too soon, the next read cannot reuse it and waits on a network request.

Usually, the app infrastructure configures GC and data retention at the `RelayEnvironment` level.

### Availability Check

`environment.check(operation)` returns an object with a `status` key (`'available'`, `'stale'` or `'missing'`). Compare `result.status` with `'stale'`, not the result.

---

## 4. Query Retention & Garbage Collection

### 4.1 What Retention Means

Retaining a query tells Relay not to delete the data for that query and variables. Multiple callers can retain a single query. As long as at least one caller retains the query, it stays in the store.

By default, query components that use `useQueryLoader` / `usePreloadedQuery` or the other Relay APIs retain the query as long as they are mounted. After they unmount, they release the query. The query might be deleted at any point after that.

### 4.2 Manual Retention with `environment.retain()`

To retain a query outside of the component lifecycle, use `environment.retain`:

```js
const {
  createOperationDescriptor,
  getRequest,
  graphql,
} = require('relay-runtime')

// Query graphql object
const query = graphql`...`;

// Construct Relay's internal representation of the query
const queryRequest = getRequest(query);
const queryDescriptor = createOperationDescriptor(
  queryRequest,
  variables
);

// Retain query; this will prevent the data for this query and
// variables from being garbage collected by Relay
const disposable = environment.retain(queryDescriptor);

// Disposing of the disposable will release the data for this query
// and variables, meaning that it can be deleted at any moment
// by Relay's garbage collection if it hasn't been retained elsewhere
disposable.dispose();
```

Relay manages query data retention for mounted query components. Product code usually does not call `retain` directly. Infra-level code, such as a Router, handles advanced cases.

### 4.3 GC Scheduler

The `gcScheduler` is a function you provide to the Relay Store. It determines when a GC execution runs:

```js
// Sample scheduler function
// Accepts a callback and schedules it to run at some future time.
function gcScheduler(run: () => void) {
  resolveImmediate(run);
}

const store = new Store(source, {gcScheduler});
```

- Without a `gcScheduler` option, Relay schedules garbage collection with the `resolveImmediate` function.
- A scheduler function can make GC scheduling less aggressive than the default, for example based on time or [scheduler](https://github.com/facebook/react/tree/main/packages/scheduler) priorities. By convention, implementations do not execute the callback immediately.

### 4.4 The Release Buffer (`gcReleaseBufferSize`)

The Relay Store holds a release buffer. It keeps a configurable number of queries retained after their original owner releases them (by default when a component that renders the query unmounts). This makes it more likely that data is reusable when navigating back to a page, tab or piece of content that was visited before.

Set the size of the release buffer with the `gcReleaseBufferSize` option of the Relay Store:

```js
const store = new Store(source, {gcReleaseBufferSize: 10});
```

- A buffer size of 0 is equivalent to no release buffer. Queries are released and collected immediately.
- By default, environments have a release buffer size of 10.

### 4.5 Query Cache Expiration (Age-Based Staleness)

The query cache expiration time affects whether a query and its variables can be fulfilled with data already in the store. Set it with the `queryCacheExpirationTime` option of the Relay Store:

```js
const store = new Store(source, {queryCacheExpirationTime: 5 * 60 * 1000 });
```

Without a query cache expiration time, staleness checks look only at whether the referenced records have been invalidated.

---

## 5. Staleness & Invalidation

By default, Relay does not consider data in the store stale, however long it has been in the cache. Data is stale when it is marked stale with the data invalidation APIs or when it is older than the query cache expiration time.

Marking data as stale is useful when you know that some data is not fresh, for example after executing a mutation. An updater function can be part of a mutation, a subscription or a local store update.

### 5.1 Global: `invalidateStore()`

The coarsest invalidation marks the whole store stale. Call `invalidateStore()` within an updater function:

```js
function updater(store) {
  store.invalidateStore();
}
```

`invalidateStore()` makes all data that was written to the store before the invalidation stale. Any query must be refetched the next time it is evaluated.

### 5.2 Record-Level: `invalidateRecord()`

To invalidate specific records, call `invalidateRecord()` within an updater function. Only queries that reference the invalidated records are stale after the invalidation.

```js
function updater(store) {
  const user = store.get('<id>');
  if (user != null) {
    user.invalidateRecord();
  }
}
```

`invalidateRecord()` on the `user` record marks that user stale. Any cached query that references that user is stale and must be refetched the next time it is evaluated.

### 5.3 Reacting: `useSubscribeToInvalidationState`

Marking the store or records stale causes queries to be refetched the next time they are evaluated. Some cases need an immediate refetch:

- Data that is already visible in the current page. No navigation occurs, so the queries for the current page are not re-evaluated, and the page shows stale data.
- Data that is rendered on a previous view that was never unmounted. If you navigate back, the queries for that view are not re-evaluated, and the view shows stale data.

For these cases, use the `useSubscribeToInvalidationState` hook:

```js
function ProfilePage(props) {
  // Example of querying data for the current page for a given user
  const data = usePreloadedQuery(
    graphql`...`,
    props.preloadedQuery,
  )

  // Here we subscribe to changes in invalidation state for the given user ID.
  // Whenever the user with that ID is marked as stale, the provided callback will
  // be executed
  useSubscribeToInvalidationState([props.userID], () => {
    // Here we can do things like:
    // - re-evaluate the query by passing a new preloadedQuery to usePreloadedQuery.
    // - imperatively refetch any data
    // - render a loading spinner or gray out the page to indicate that refetch
    //   is happening.
  })

  return (...);
}
```

- `useSubscribeToInvalidationState` takes an array of ids and a callback. Whenever any record for those ids is marked stale, the callback fires.
- In the callback, refetch or update the views that render stale data. For example, keep the `preloadedQuery` in state and set a new one in the callback to re-execute the top-level `usePreloadedQuery`. That query is stale, so it is refetched even if the data is cached in the store.

### 5.4 Stale Definition

A stale query is one that can be fulfilled with records from the store, and:

- the time since it was last fetched is greater than the query cache expiration time, or
- it contains at least one record that was invalidated.

The staleness check occurs when a new request is made (for example in a call to `loadQuery`). Components that reference stale data continue to render that data. Additional requests that would be fulfilled with stale data go to the network.

---

## 6. Rendering Partially Cached Data

*Partial rendering* is the ability to immediately render a query that is partially cached. The cached parts render without waiting for the full query.

### 6.1 Fragments as Boundaries

A fragment component suspends if any data it declared locally is missing during render and is being fetched. It suspends until its parent query is fetched. Relay considers data missing only if it is declared locally and missing. Data selected within fragment spreads does not affect whether the outer query or fragment has missing data.

Take this fragment component:

```js
/**
 * UsernameComponent.react.js
 *
 * Fragment Component
 */

import type {UsernameComponent_user$key} from 'UsernameComponent_user.graphql';

const React = require('React');
const {graphql, useFragment} = require('react-relay');

type Props = {
  user: UsernameComponent_user$key,
};

function UsernameComponent(props: Props) {
  const user = useFragment(
    graphql`
      fragment UsernameComponent_user on User {
        username
      }
    `,
    props.user,
  );
  return (...);
}

module.exports = UsernameComponent;
```

If only the `name` of the `User` with `{id: 4}` is cached, the query that includes this fragment renders, because `name` is available. `UsernameComponent` then suspends, because `username` is missing. A network request always starts if any piece of data for the full query, including fragments, is missing, regardless of the `fetchPolicy`.

Without a `Suspense` component, the suspension bubbles up and suspends the entire app. Wrap `UsernameComponent` in `Suspense` so the other parts render:

```js
/**
 * HomeTab.react.js
 *
 * Query Component
 */

const React = require('React');
const {Suspense} = require('React');
const {graphql, usePreloadedQuery} = require('react-relay');

const UsernameComponent = require('./UsernameComponent.react');


function HomeTab() {
  const data = usePreloadedQuery(
    graphql`
      query AppQuery($id: ID!) {
        user(id: $id) {
          name
          ...UsernameComponent_user
        }
      }
    `,
    props.queryRef,
  );

  return (
    <>
      <h1>{data.user?.name}</h1>

      {/*
        Wrap the UserComponent in Suspense to allow other parts of the
        App to be rendered even if the username is missing.
      */}
      <Suspense fallback={<LoadingSpinner label="Fetching username" />}>
        <UsernameComponent user={data.user} />
      </Suspense>
    </>
  );
}
```

The same process applies to nested fragments. If the data a fragment requires is cached, the fragment component renders, whether or not data for its child or descendant fragments is missing. Wrap a child fragment with missing data in `Suspense` so other fragments and parts of the app continue to render.

---

## 7. Filling In Missing Data: `missingFieldHandlers`

Relay reuses data that is cached for a query fetched before. When different queries point to the same data, Relay does not know that by default. Take these two queries:

```js
// Query 1

query UserQuery {
  user(id: 4) {
    name
  }
}
```

```js
// Query 2

query NodeQuery {
  node(id: 4) {
    ... on User {
      name
    }
  }
}
```

They reference the same data. To reuse the cached data of one query when rendering the other, provide `missingFieldHandlers` to the `RelayEnvironment`. They encode that a `node(id: 4)` "is the same as" `user(id: 4)`.

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
      if (
        record != null &&
        record.getType() === ROOT_TYPE &&
        field.name === 'user' &&
        argValues.hasOwnProperty('id')
      ) {
        // If field is user(id: $id), look up the record by the value of $id
        return argValues.id;
      }
      if (
        record != null &&
        record.getType() === ROOT_TYPE &&
        field.name === 'story' &&
        argValues.hasOwnProperty('story_id')
      ) {
        // If field is story(story_id: $story_id), look up the record by the
        // value of $story_id.
        return argValues.story_id;
      }
      return undefined;
    },
    kind: 'linked',
  },
];

const environment = new Environment({/*...*/, missingFieldHandlers});
```

- `missingFieldHandlers` is an array of handlers. Each handler specifies a `handle` function and the kind of missing fields it handles:
  - `'scalar'`: a field that contains a scalar value, for example a number or a string.
  - `'linked'`: a field that references another object, not a scalar.
- The `handle` function takes the missing field, the record that field belongs to, and the arguments passed to the field in the current execution of the query.
  - For a `'scalar'` field, `handle` returns a scalar value to use as the value of the missing field.
  - For a `'linked'` field, `handle` returns an ID that references another object in the store to use in place of the missing field.
- When Relay fulfills a query from the local cache and detects missing data, it runs the matching missing field handlers before it declares the data missing.

---

## 8. Updating Connections

To add an edge to a connection after a mutation, create the edge with `ConnectionHandler.createEdge`:

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

Add the new edge to the connection with `ConnectionHandler.insertEdgeAfter` or `ConnectionHandler.insertEdgeBefore`:

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

See [updating-data.md](./updating-data.md) for more on connection updaters.

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Data gone after brief unmount/remount | Release buffer too small; GC ran | Increase `gcReleaseBufferSize` |
| Two queries for the same record do not share cached data | Relay does not know that the two root fields reference the same record | Add `missingFieldHandlers` for the `node`/`user` mappings |
| Stale data still visible after mutation | Invalidated but component already mounted | Add `useSubscribeToInvalidationState` and refetch in the callback |
| `store-or-network` won't refetch fresh server data | Query is present and not stale | Use `store-and-network` or set `queryCacheExpirationTime` |
| Fragment at leaf suspends the whole screen | Missing local `<Suspense>` boundary | Wrap the partially cached fragment in its own `<Suspense>` |
| `environment.check(query) === 'stale'` is never true | `check` returns an object | Compare `environment.check(query).status` |

---

## 10. Summary

- Default to `store-or-network`. Use `store-and-network` to always send a request, `network-only` to ignore the cache, and `store-only` for local data.
- Query components retain queries while mounted; the release buffer smooths navigation.
- Tune the lifecycle with `gcReleaseBufferSize`, `gcScheduler` and `queryCacheExpirationTime` on the `Store`.
- Mark data stale with `invalidateStore()` / `invalidateRecord()` inside an updater. Use `useSubscribeToInvalidationState` to refetch visible stale data.
- Wrap a fragment that can render with partial data in its own `<Suspense>`.
- Use `missingFieldHandlers` to teach Relay that different query shapes reference the same data.
