# React Relay Hooks

Complete reference for every React Relay hook. All examples are hooks-only
(no `QueryRenderer`, no `createFragmentContainer`). Types shown are the public
surface you will see in `react-relay` TypeScript definitions.

All hooks must be used inside a component tree wrapped with
`<RelayEnvironmentProvider environment={env}>`. Data-fetching hooks integrate
with React `Suspense` and React error boundaries.

---

## RelayEnvironmentProvider

Sets the Relay environment in React context. Render 1 provider at the root of the app. Every Relay hook in a descendant reads its environment from the nearest provider.

```tsx
import { RelayEnvironmentProvider } from 'react-relay';
import { Environment, Network, Observable, RecordSource, Store } from 'relay-runtime';

const environment = new Environment({
  network: Network.create((params, variables) =>
    Observable.from(
      fetch('/graphql', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: params.text, variables }),
      }).then(response => response.json()),
    ),
  ),
  store: new Store(new RecordSource()),
});

export function Root() {
  return (
    <RelayEnvironmentProvider environment={environment}>
      <App />
    </RelayEnvironmentProvider>
  );
}
```

| Prop | Behavior |
|---|---|
| `environment` | Required. The environment for all descendant hooks. |
| `getEnvironmentForActor` | Optional. Resolves the environment of an actor in multi-actor setups. It exists in the Flow type only; the TypeScript `Props` omits it. |

- Create the environment once, outside the component. A new `environment` prop makes `useSubscription` resubscribe and `useMutation` reset its `isInFlight` state.
- A hook rendered outside a provider throws.

---

## useFragment

Reads data for a fragment off a parent-provided fragment key. This is the most
common hook — every leaf component that needs GraphQL data should use it.

### Signature

```ts
function useFragment<TKey extends KeyType>(
  fragment: GraphQLTaggedNode,
  fragmentReference: TKey,
): KeyTypeData<TKey>;

// Nullable variant (for optional fragment refs)
function useFragment<TKey extends KeyType | null | undefined>(
  fragment: GraphQLTaggedNode,
  fragmentReference: TKey,
): KeyTypeData<TKey> | null | undefined;
```

- `fragment` — a `graphql` template literal defining the fragment.
- `fragmentReference` — the opaque `<FragmentName>$key` value passed from a
  parent that spreads this fragment in its query or fragment.

Returns a read-only object matching the fragment's selection set, typed via the
generated `<FragmentName>$data` type.

### Example

```tsx
import { graphql, useFragment } from 'react-relay';
import type { UserCard_user$key } from './__generated__/UserCard_user.graphql';

type Props = { userRef: UserCard_user$key };

export function UserCard({ userRef }: Props) {
  const user = useFragment(
    graphql`
      fragment UserCard_user on User {
        id
        name
        avatar { uri }
      }
    `,
    userRef,
  );

  return (
    <article>
      <img src={user.avatar?.uri ?? ''} alt="" />
      <h2>{user.name}</h2>
    </article>
  );
}
```

### Suspense behavior

Suspends only if the fragment's data is currently being fetched by a parent
query (for example, during a `refetch` or `loadNext` call that covers this
fragment). In steady state, `useFragment` is synchronous.

### Pitfalls

- Do not read props from the fragment `$data` type directly; always declare
  `Props` in terms of `<FragmentName>$key`. This is enforced by
  `eslint-plugin-relay/no-fragment-missing-key`.
- Fragments must be spread in an ancestor query or fragment, otherwise the
  data will be missing and the component will never render.
- The returned object is frozen. Do not mutate it — use mutations or local
  updates to change data.

---

## usePreloadedQuery

Reads the result of a query that was started outside of render (via
`useQueryLoader` or the imperative `loadQuery`). This is the preferred query
hook because it enables render-as-you-fetch.

### Signature

```ts
function usePreloadedQuery<TQuery extends OperationType>(
  gqlQuery: GraphQLTaggedNode,
  preloadedQuery: PreloadedQuery<TQuery>,
  options?: { UNSTABLE_renderPolicy?: 'full' | 'partial' },
): TQuery['response'];
```

- `gqlQuery` — the same `graphql` query tag used to create the preloaded
  reference.
- `preloadedQuery` — the `PreloadedQuery<TQuery>` returned by
  `useQueryLoader` or `loadQuery`. The fetch policy and the network cache
  config come from the call that created this reference.
- `options.UNSTABLE_renderPolicy` — same meaning as on `useLazyLoadQuery`.

Returns the query response typed as `TQuery['response']`.

### Example

```tsx
import { Suspense } from 'react';
import {
  graphql,
  useQueryLoader,
  usePreloadedQuery,
  type PreloadedQuery,
} from 'react-relay';
import type { AppQuery as AppQueryType } from './__generated__/AppQuery.graphql';

const AppQuery = graphql`
  query AppQuery($id: ID!) {
    user: node(id: $id) {
      ... on User { name }
    }
  }
`;

function UserView({ queryRef }: { queryRef: PreloadedQuery<AppQueryType> }) {
  const data = usePreloadedQuery(AppQuery, queryRef);
  return <h1>{data.user?.name ?? 'Unknown'}</h1>;
}

export function App() {
  const [queryRef, loadQuery, disposeQuery] =
    useQueryLoader<AppQueryType>(AppQuery);

  return (
    <>
      <button onClick={() => loadQuery({ id: '4' })}>Load</button>
      <button onClick={disposeQuery}>Clear</button>
      <Suspense fallback={<span>Loading user...</span>}>
        {queryRef && <UserView queryRef={queryRef} />}
      </Suspense>
    </>
  );
}
```

### Suspense behavior

Suspends if the underlying request is still pending. Throws if the request
failed — catch with an error boundary. Returns synchronously once data is in
the store.

### Pitfalls

- The `queryRef` passed to `usePreloadedQuery` must have been created for the
  same query tag; mismatches cause runtime errors.
- A `null` `queryRef` is invalid to pass — guard with `queryRef &&` in JSX.
  On v21 the Flow overload accepts `null` and the hook returns `null`
  (`usePreloadedQuery.js`). On v20 a `null` ref throws, and the TypeScript
  type on both versions requires a non-null ref.
- Passing a disposed ref logs a dev warning (`isDisposed`); the warning text
  states that it becomes a hard error in a future release.
- The preloaded query is automatically retained until disposed or until the
  consuming component unmounts (when using `useQueryLoader`).

---

## useLazyLoadQuery

Fetches a query during render. Convenient for prototypes but susceptible to
request waterfalls. Prefer `usePreloadedQuery` in production.

### Signature

```ts
function useLazyLoadQuery<TQuery extends OperationType>(
  gqlQuery: GraphQLTaggedNode,
  variables: TQuery['variables'],
  options?: {
    fetchPolicy?:
      | 'store-or-network'
      | 'store-and-network'
      | 'network-only'
      | 'store-only';
    fetchKey?: string | number;
    networkCacheConfig?: CacheConfig;
    UNSTABLE_renderPolicy?: 'full' | 'partial';
  },
): TQuery['response'];
```

### Options

| Option | Default | Behavior |
|---|---|---|
| `fetchPolicy` | `"store-or-network"` | See table below. |
| `fetchKey` | `undefined` | Changing this value forces the query to refetch even if variables are the same. |
| `networkCacheConfig` | `{ force: true }` | Passed to the network layer. `force: true` bypasses any response cache. |
| `UNSTABLE_renderPolicy` | `'partial'` | `'full'` suspends unless the entire query is cached. The `UNSTABLE_defaultRenderPolicy` option of `new Environment({...})` sets the default; its own default is `'partial'`. |

### fetch policies

- `store-or-network` — Serve from cache if all data is present; otherwise
  fetch.
- `store-and-network` — Serve cache immediately and always refetch.
- `network-only` — Always fetch; suspend until network responds.
- `store-only` — Read cache only; never fetch.

### Example

```tsx
import { graphql, useLazyLoadQuery } from 'react-relay';
import type { FeedQuery as FeedQueryType } from './__generated__/FeedQuery.graphql';

export function Feed({ limit }: { limit: number }) {
  const data = useLazyLoadQuery<FeedQueryType>(
    graphql`
      query FeedQuery($limit: Int!) {
        feed(first: $limit) {
          edges { node { id title } }
        }
      }
    `,
    { limit },
    { fetchPolicy: 'store-and-network' },
  );

  return (
    <ul>
      {data.feed?.edges?.map(edge =>
        edge?.node ? <li key={edge.node.id}>{edge.node.title}</li> : null,
      )}
    </ul>
  );
}
```

### Suspense behavior

Suspends when fetching in render (any policy that hits the network with a
cold cache). Wrap the component in a `<Suspense>` boundary.

### Pitfalls

- Causes render waterfalls — the network request starts only when this
  component mounts, not when its parent starts fetching.
- Recreating the `variables` object identity on every render still works
  (Relay compares by value), but avoid constructing it inline when `fetchKey`
  changes are not intended.
- Below a `usePreloadedQuery`, a lazy query can create a waterfall. The docs
  prefer `usePreloadedQuery`.
- Re-rendering with the same variables does not refetch. New variables, a new
  `fetchKey`, or an unmount followed by a mount start a new evaluation
  against the store and `fetchPolicy`.
- A failed request throws during render. Catch it with an error boundary and
  retry with a new `fetchKey` (see "Retrying after an error").

---

## useQueryLoader

Manages the lifecycle of a `PreloadedQuery`: returns a ref, a loader, and a
disposer. Pair it with `usePreloadedQuery` for render-as-you-fetch.

### Signature

```ts
function useQueryLoader<TQuery extends OperationType>(
  query: GraphQLTaggedNode,
  initialQueryRef?: PreloadedQuery<TQuery> | null,
): [
  queryRef: PreloadedQuery<TQuery> | null | undefined,
  loadQuery: (
    variables: TQuery['variables'],
    options?: {
      fetchPolicy?: 'store-or-network' | 'store-and-network' | 'network-only';
      networkCacheConfig?: CacheConfig;
    },
  ) => void,
  disposeQuery: () => void,
];
```

### Example

```tsx
import { Suspense, useEffect } from 'react';
import {
  graphql,
  useQueryLoader,
  usePreloadedQuery,
  type PreloadedQuery,
} from 'react-relay';
import type { ProfileQuery as ProfileQueryType } from './__generated__/ProfileQuery.graphql';

const ProfileQuery = graphql`
  query ProfileQuery($id: ID!) {
    node(id: $id) { ... on User { id name bio } }
  }
`;

function Profile({ queryRef }: { queryRef: PreloadedQuery<ProfileQueryType> }) {
  const data = usePreloadedQuery(ProfileQuery, queryRef);
  if (!data.node) return <p>Not found</p>;
  return (
    <section>
      <h1>{data.node.name}</h1>
      <p>{data.node.bio}</p>
    </section>
  );
}

export function ProfileRoute({ userId }: { userId: string }) {
  const [queryRef, loadQuery, disposeQuery] =
    useQueryLoader<ProfileQueryType>(ProfileQuery);

  useEffect(() => {
    loadQuery({ id: userId }, { fetchPolicy: 'store-or-network' });
    return () => disposeQuery();
  }, [userId, loadQuery, disposeQuery]);

  return (
    <Suspense fallback={<p>Loading profile...</p>}>
      {queryRef && <Profile queryRef={queryRef} />}
    </Suspense>
  );
}
```

### Suspense behavior

`useQueryLoader` itself does not suspend. Suspension happens inside
`usePreloadedQuery` when the consumer reads the ref.

### Pitfalls

- Never call `loadQuery` or `disposeQuery` during render — call them from
  effects, event handlers, or routing callbacks.
- Calling `loadQuery` while a previous ref is outstanding disposes the old
  one automatically; you do not need to call `disposeQuery` first.
- The hook disposes the last ref when the component unmounts — do not hold
  references elsewhere or you will leak retained data.
- The hook owns `initialQueryRef` (for example a ref that a router created
  with `loadQuery`). It disposes that ref when `loadQuery` replaces it or when
  the component unmounts.
- `disposeQuery` also cancels the request when the request is still in flight.
- `loadQuery` and `disposeQuery` do nothing after the component unmounts.

---

## loadQuery (imperative)

Starts a query outside a component and returns a `PreloadedQuery`. Use it for
the initial load of the app or in a router, where no component owns the
reference. Pass the reference to `usePreloadedQuery`.

```ts
import { loadQuery } from 'react-relay';
import type { AppQuery as AppQueryType } from './__generated__/AppQuery.graphql';

const queryRef = loadQuery<AppQueryType>(
  environment,
  AppQuery,
  { id: '4' },
  { fetchPolicy: 'store-or-network' },
);

// After no component renders the reference:
queryRef.dispose();
```

| Argument | Behavior |
|---|---|
| `environment` | The `IEnvironment` that runs the request. |
| `query` | A `graphql` tag, or a `@preloadable` query's `$Parameters` module. |
| `variables` | Query variables. |
| `options.fetchPolicy` | `'store-or-network'` (default), `'store-and-network'`, `'network-only'`. The source also accepts `'store-only'`, which retains the data and sends no request. |
| `options.networkCacheConfig` | The source always sets `force: true` on the config. |
| `environmentProviderOptions` | Optional 5th argument. Entry points use it. |

- **Dispose every reference.** The store retains the query data until
  `.dispose()` runs. A reference that is never disposed leaks its data into
  the store. `dispose()` also cancels the request when the request is in
  flight. Prefer `useQueryLoader`, which disposes for you.
- The store receives the response as soon as the query and the data are
  both available, even when no component renders the ref yet.
- Call `loadQuery` from an event handler or router callback. The docs state
  that `loadQuery` throws during render. The v20.1.1 and v21.0.1 source has no
  render-phase check, so a call in render creates a new undisposed reference
  on every render.
- The docs state that only `dispose` is a stable property of the return value.

---

## Retrying after an error

`usePreloadedQuery` and `useLazyLoadQuery` throw when the request fails. An
error boundary catches the error. A retry needs a new request. The retry
trigger depends on the query hook.

```tsx
import { Component, type ReactNode } from 'react';

type Props = {
  children: (state: { fetchKey: number }) => ReactNode;
  fallback: (args: { error: Error; retry: () => void }) => ReactNode;
  onRetry?: () => void;
};
type State = { error: Error | null; fetchKey: number };

export class ErrorBoundaryWithRetry extends Component<Props, State> {
  state: State = { error: null, fetchKey: 0 };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  retry = () => {
    this.props.onRetry?.();
    this.setState(prev => ({ error: null, fetchKey: prev.fetchKey + 1 }));
  };

  render() {
    const { error, fetchKey } = this.state;
    if (error) return this.props.fallback({ error, retry: this.retry });
    return this.props.children({ fetchKey });
  }
}
```

- **`useLazyLoadQuery`:** pass `fetchKey` from the boundary to the hook,
  `useLazyLoadQuery(query, variables, { fetchKey })`. The new key re-evaluates
  and refetches the query.
- **`useQueryLoader` / `loadQuery`:** pass `onRetry={() => loadQuery(variables)}`.
  The call creates a new `PreloadedQuery`, and `usePreloadedQuery` reads the
  new ref.
- To show a message from a GraphQL error, model the error as a schema type
  (for example `result: Result | Error`). The docs recommend this approach.

---

## Refreshing and refetching without Suspense

`loadQuery(variables, { fetchPolicy: 'network-only' })` refreshes a query
with the same variables. A different `variables` object refetches. Both calls
make `usePreloadedQuery` suspend, which replaces the visible content with the
`Suspense` fallback. To keep the content on screen, fetch with `fetchQuery`,
track the loading state yourself, and then read the cached data.

```tsx
import { useState } from 'react';
import { fetchQuery, useQueryLoader, useRelayEnvironment } from 'react-relay';

// Inside a component:
const environment = useRelayEnvironment();
const [queryRef, loadQuery] = useQueryLoader<AppQueryType>(AppQuery);
const [isRefreshing, setIsRefreshing] = useState(false);

const refresh = (variables: AppQueryType['variables']) => {
  if (isRefreshing) return;
  setIsRefreshing(true);
  fetchQuery<AppQueryType>(environment, AppQuery, variables).subscribe({
    complete: () => {
      setIsRefreshing(false);
      loadQuery(variables, { fetchPolicy: 'store-only' });
    },
    error: () => setIsRefreshing(false),
  });
};
```

- `fetchQuery` writes the response to the store. `store-only` makes the
  following `loadQuery` read that data without a request or a suspension.
- For `useLazyLoadQuery`, replace the `loadQuery` call with a state update
  that sets `{ fetchKey: previous + 1, fetchPolicy: 'store-only' }`.
- The `loadQuery` options type of `useQueryLoader` above lists 3 policies. The
  runtime also accepts `'store-only'`, and the v21 docs use it in this pattern.

---

## useRefetchableFragment

Like `useFragment`, plus a `refetch` function that re-runs the fragment's
auto-generated query with new variables. The fragment must declare
`@refetchable(queryName: "...")`.

### Signature

```ts
function useRefetchableFragment<TQuery extends OperationType, TKey extends KeyType>(
  fragment: GraphQLTaggedNode,
  fragmentReference: TKey,
): [
  data: KeyTypeData<TKey>,
  refetch: (
    variables: Partial<TQuery['variables']>,
    options?: {
      fetchPolicy?:
        | 'store-or-network'
        | 'store-and-network'
        | 'network-only'
        | 'store-only';
      onComplete?: (error: Error | null) => void;
      UNSTABLE_renderPolicy?: 'full' | 'partial';
    },
  ) => Disposable,
];
```

### Example

```tsx
import { startTransition, useState } from 'react';
import { graphql, useRefetchableFragment } from 'react-relay';
import type {
  TranslatablePost_post$key,
} from './__generated__/TranslatablePost_post.graphql';
import type {
  TranslatablePostRefetchQuery,
} from './__generated__/TranslatablePostRefetchQuery.graphql';

type Props = { postRef: TranslatablePost_post$key };

export function TranslatablePost({ postRef }: Props) {
  const [isPending, setPending] = useState(false);
  const [data, refetch] = useRefetchableFragment<
    TranslatablePostRefetchQuery,
    TranslatablePost_post$key
  >(
    graphql`
      fragment TranslatablePost_post on Post
      @refetchable(queryName: "TranslatablePostRefetchQuery")
      @argumentDefinitions(lang: { type: "Lang", defaultValue: EN }) {
        id
        body(lang: $lang)
      }
    `,
    postRef,
  );

  return (
    <article>
      <p>{data.body}</p>
      <button
        disabled={isPending}
        onClick={() => {
          setPending(true);
          startTransition(() => {
            refetch(
              { lang: 'ES' },
              {
                fetchPolicy: 'store-or-network',
                onComplete: () => setPending(false),
              },
            );
          });
        }}
      >
        Translate to Spanish
      </button>
    </article>
  );
}
```

### Refetch options

| Option | Behavior |
|---|---|
| `fetchPolicy` | Same policies as `useLazyLoadQuery`. See "Fetch policy by API". |
| `onComplete` | Runs when the request completes, including incremental payloads. Receives an `Error` when the request fails, otherwise `null`. |
| `UNSTABLE_renderPolicy` | `'full'` or `'partial'`, as on `useLazyLoadQuery`. |

`refetch` returns a `Disposable`. `dispose()` cancels the request.

### Pending state with `useTransition`

`useTransition` returns `isPending`, so the component needs no extra state.
Call `refetch` inside `startTransition`. React keeps the current data on
screen until the new data is ready. Update unrelated state (here the input
value) outside the transition so that it renders at once.

```tsx
import { useState, useTransition } from 'react';

const [isPending, startTransition] = useTransition();
const [search, setSearch] = useState('');
const [data, refetch] = useRefetchableFragment<ContactsRefetchQuery, Contacts_viewer$key>(
  ContactsFragment,
  viewerRef,
);

const onChange = (value: string) => {
  setSearch(value);
  startTransition(() => {
    refetch({ search: value });
  });
};
```

### Suspense behavior

Suspends when the refetch is in flight and the requested data is not already
cached. Use `startTransition` to avoid flashing fallbacks and keep the old
data visible while the new data is loading.

### Pitfalls

- Missing `@refetchable` directive — the hook throws an error.
- Fragment must be on `Viewer`, `Query`, or a type implementing `Node`.
- Variables you omit fall back to the values from the original parent query.
- If the fragment key is optional, pass all non-optional variables to
  `refetch`, including the object's ID.
- `refetch` re-renders the component; if you are not inside a transition,
  the subtree can suspend and replace the UI with the fallback.
- Calling `refetch` after the component unmounts logs a dev warning and
  returns a `Disposable` that does nothing. Clear timers and async callbacks on
  unmount.

---

## usePaginationFragment

Like `useRefetchableFragment`, plus helpers for paginating a `@connection`.
The fragment must declare both `@refetchable` and `@connection`.

### Signature

```ts
function usePaginationFragment<TQuery extends OperationType, TKey extends KeyType>(
  fragment: GraphQLTaggedNode,
  fragmentReference: TKey,
): {
  data: KeyTypeData<TKey>;
  loadNext: (count: number, options?: { onComplete?: (err: Error | null) => void }) => Disposable;
  loadPrevious: (count: number, options?: { onComplete?: (err: Error | null) => void }) => Disposable;
  hasNext: boolean;
  hasPrevious: boolean;
  isLoadingNext: boolean;
  isLoadingPrevious: boolean;
  refetch: (
    variables: Partial<TQuery['variables']>,
    options?: {
      fetchPolicy?:
        | 'store-or-network'
        | 'store-and-network'
        | 'network-only'
        | 'store-only';
      onComplete?: (error: Error | null) => void;
      UNSTABLE_renderPolicy?: 'full' | 'partial';
    },
  ) => Disposable;
};
```

### Example

```tsx
import { graphql, usePaginationFragment } from 'react-relay';
import type {
  FriendsList_user$key,
} from './__generated__/FriendsList_user.graphql';
import type {
  FriendsListPaginationQuery,
} from './__generated__/FriendsListPaginationQuery.graphql';

type Props = { userRef: FriendsList_user$key };

export function FriendsList({ userRef }: Props) {
  const {
    data,
    loadNext,
    hasNext,
    isLoadingNext,
  } = usePaginationFragment<FriendsListPaginationQuery, FriendsList_user$key>(
    graphql`
      fragment FriendsList_user on User
      @refetchable(queryName: "FriendsListPaginationQuery")
      @argumentDefinitions(
        count: { type: "Int", defaultValue: 10 }
        cursor: { type: "String" }
      ) {
        friends(first: $count, after: $cursor)
          @connection(key: "FriendsList_user_friends") {
          edges {
            node { id name }
          }
        }
      }
    `,
    userRef,
  );

  return (
    <>
      <ul>
        {data.friends?.edges?.map(edge =>
          edge?.node ? <li key={edge.node.id}>{edge.node.name}</li> : null,
        )}
      </ul>
      {hasNext && (
        <button disabled={isLoadingNext} onClick={() => loadNext(10)}>
          {isLoadingNext ? 'Loading...' : 'Load more'}
        </button>
      )}
    </>
  );
}
```

### `loadNext` and `loadPrevious` options

| Option | Behavior |
|---|---|
| `onComplete` | Runs when the request completes, including incremental payloads. Receives an `Error` when the request fails, otherwise `null`. |
| `UNSTABLE_extraVariables` | Adds variables to the pagination request. The name marks the option as unstable. |

Both functions return a `Disposable`. `dispose()` cancels the request.
`hasNext` and `hasPrevious` are `true` while more items exist in that
direction.

With `usePaginationFragment`, the compiler adds the `pageInfo` and `cursor`
selections of the connection, so the fragment needs only `edges { node }`.
This statement comes from the v21 docs; the v20 docs omit it.

### Bi-directional pagination

`usePaginationFragment` returns both directions. Backward pagination needs the
`before` and `last` arguments on the connection field next to `after` and
`first`. Both directions can load at the same time. The parent query or
`@argumentDefinitions` declares the 4 variables.

```tsx
const { data, loadPrevious, hasPrevious, loadNext, hasNext } =
  usePaginationFragment<FriendsListPaginationQuery, FriendsList_user$key>(
    graphql`
      fragment FriendsList_user on User
      @refetchable(queryName: "FriendsListPaginationQuery") {
        name
        friends(after: $after, before: $before, first: $first, last: $last)
          @connection(key: "FriendsList_user_friends") {
          edges { node { id name } }
        }
      }
    `,
    userRef,
  );

// {hasPrevious && <button onClick={() => loadPrevious(10)}>Load earlier</button>}
```

### Streaming pagination

Use `@stream_connection` in place of `@connection` to receive the items of a
connection as the server produces them. The directive takes the arguments of
`@connection` and the optional `initial_count: Int` (default 0). The first
payload contains `initial_count` items, and the rest stream in. The connection
updates and the component re-renders for each streamed item.

```graphql
friends(first: $count, after: $cursor)
  @stream_connection(key: "FriendsList_user_friends", initial_count: 2) {
  edges { node { name } }
}
```

### Refetching a connection with new filters

`refetch` fetches the fragment again with new variables. Variables that
`refetch` omits keep their original values. The call disposes any `loadNext`
or `loadPrevious` request that is in flight. A filter argument that appears in
`filters` of `@connection` creates a separate connection record for each
value, so list the arguments that change the items or the order.

```graphql
fragment CommentList_story on Story
@argumentDefinitions(
  count: { type: "Int", defaultValue: 10 }
  cursor: { type: "String" }
  orderBy: { type: "CommentOrder", defaultValue: NEWEST }
)
@refetchable(queryName: "CommentListPaginationQuery") {
  comments(first: $count, after: $cursor, order_by: $orderBy)
    @connection(key: "CommentList_story_comments", filters: ["order_by"]) {
    edges { node { id body } }
  }
}
```

```tsx
startTransition(() => {
  refetch({ orderBy: 'OLDEST' }, { fetchPolicy: 'network-only' });
});
```

Use 1 `usePaginationFragment` call per connection. A component with 2
connections calls the hook twice, and the docs recommend 1 connection per
component.

### Suspense behavior

- `loadNext` and `loadPrevious` do not suspend the component that calls
  them. They set `isLoadingNext` / `isLoadingPrevious`, then append results
  to the connection. New child components that render the added items can
  suspend, so wrap the list in `Suspense` and call `loadNext` inside
  `startTransition`.
- `refetch` suspends the same way `useRefetchableFragment`'s does (wrap in
  `startTransition` to avoid fallback flashes).
- The component suspends if fragment data is missing while a parent query is
  fetching.

### Pitfalls

- The connection key must be unique and stable — do not interpolate variables
  into it; use `@connection(filters: [...])` instead.
- `loadNext(count)` passes `count` as the new `first` variable; paginate
  using the same variable name declared in `@argumentDefinitions`.
- Calling `loadNext` while one is already in flight is a no-op.
  The call also does nothing while the parent query is still loading, when
  the fragment data is `null`, and after the component unmounts. Except after
  unmount, `onComplete(null)` runs at once in each of these cases.
- Unmounting the component cancels a request that is in flight.
- Only pagination variables change between loads — other variables are
  locked to whatever the parent query fetched.

---

## usePrefetchableForwardPaginationFragment

Experimental. Works like `usePaginationFragment` for forward pagination, and
prefetches `bufferSize` items that it holds back from display. `loadNext`
takes items from that buffer first.

```tsx
const { data, edges, loadNext, hasNext, isLoadingNext, refetch } =
  usePrefetchableForwardPaginationFragment(
    graphql`
      fragment FriendsList_user on User
      @argumentDefinitions(
        count: { type: "Int", defaultValue: 10 }
        cursor: { type: "String" }
      )
      @refetchable(queryName: "FriendsListPaginationQuery") {
        friends(first: $count, after: $cursor)
          @connection(key: "FriendsList_user_friends", prefetchable_pagination: true) {
          edges { node { name } }
        }
      }
    `,
    userRef,
    bufferSize,
    // optional: initialSize, prefetchingLoadMoreOptions, minimumFetchSize
  );
```

- Set `prefetchable_pagination: true` on `@connection`; the hook throws
  without it.
- Render from the returned `edges`. The edges in `data` include the buffer.
- `isLoadingNext` stays `false` during an automatic prefetch.

| Argument | Behavior |
|---|---|
| `bufferSize` | Number of items to keep prefetched. The hook fills the buffer in an effect. |
| `initialSize` | Optional. Number of items to show on the first render. Without it the hook shows all available items on the first render and after a refetch. |
| `prefetchingLoadMoreOptions` | Optional. `{ onComplete }` for the automatic prefetch. `onComplete` receives an `Error` when the prefetch fails. |
| `minimumFetchSize` | Optional. Minimum number of items in any request. |

- The hook supports forward pagination only: `loadNext`, `hasNext` and
  `isLoadingNext`. `hasNext` is `true` when more items exist on the server or
  in the buffer.
- `loadNext(count)` shows items from the buffer first and sends a request when
  the buffer has fewer than `count` items. `loadNext` returns `void`.

---

## useMutation

Executes a GraphQL mutation, with support for optimistic updates and store
updaters.

### Signature

```ts
function useMutation<TMutation extends MutationParameters>(
  mutation: GraphQLTaggedNode,
  commitMutationFn?: (env: IEnvironment, config: MutationConfig<TMutation>) => Disposable,
): [
  commit: (config: {
    variables: TMutation['variables'];
    onCompleted?: (response: TMutation['response'], errors: PayloadError[] | null) => void;
    onError?: (error: Error) => void;
    optimisticResponse?: TMutation['rawResponse'];
    optimisticUpdater?: SelectorStoreUpdater<TMutation['response']>;
    updater?: SelectorStoreUpdater<TMutation['response']>;
    uploadables?: Record<string, File | Blob>;
  }) => Disposable,
  isInFlight: boolean,
];
```

### Example

```tsx
import { graphql, useMutation } from 'react-relay';
import type { LikeButtonMutation } from './__generated__/LikeButtonMutation.graphql';

export function LikeButton({ feedbackId, liked }: { feedbackId: string; liked: boolean }) {
  const [commit, isInFlight] = useMutation<LikeButtonMutation>(graphql`
    mutation LikeButtonMutation($input: FeedbackLikeInput!) {
      feedbackLike(input: $input) {
        feedback {
          id
          viewerDidLike
          likeCount
        }
      }
    }
  `);

  return (
    <button
      disabled={isInFlight}
      onClick={() => {
        commit({
          variables: { input: { id: feedbackId } },
          optimisticResponse: {
            feedbackLike: {
              feedback: {
                id: feedbackId,
                viewerDidLike: !liked,
                likeCount: liked ? 0 : 1, // adjust as needed
              },
            },
          },
          onError: err => console.error(err),
        });
      }}
    >
      {liked ? 'Unlike' : 'Like'}
    </button>
  );
}
```

### Commit options

- `variables` — mutation variables.
- `onCompleted(response, errors)` — fired when the server returns. `errors`
  is the `errors` array from the GraphQL response, if any. `errors` is `null`
  when the response has none. `response` is the mutation selection read from
  the store after the updaters and the declarative directives run: data inside
  masked fragment spreads is absent, and a record that `@deleteRecord` removed
  reads as `null`.
- `onError(error)` — network or unexpected failure.
- `onUnsubscribe` — fired when the returned `Disposable` is disposed.
- `optimisticResponse` — synthetic response applied to the store immediately;
  rolled back automatically if the request errors.
- `optimisticUpdater` — imperative store mutation for cases the
  `optimisticResponse` cannot express (e.g. inserting into a connection).
- `updater` — imperative store mutation applied after the real response.
  Use for connection edits and anything not expressed by field selections.
  The signature is `(store: RecordSourceSelectorProxy, data: TMutation['response'] | null | undefined) => void`.
  Relay reverts the optimistic changes before it runs `updater`.
- `configs` — array of `DeclarativeMutationConfig`. The TypeScript and Flow
  types of the commit config include it.
- `uploadables` — `File` / `Blob` map for multipart uploads.

### Suspense behavior

Does not suspend. `isInFlight` drives loading UI.

### Pitfalls

- Disposing after `onCompleted` does not revert store changes — only queued
  optimistic updates are revertible.
- `optimisticResponse` must match the mutation's `rawResponse` shape,
  including `__typename` where selections are polymorphic. Generate
  `rawResponse` types by adding `@raw_response_type` to the mutation.
- Prefer `optimisticResponse` over `optimisticUpdater` for simple field
  changes; updaters run in addition to the response, not instead of it.
- `commit` should be called from event handlers, not render.
- `commitMutationFn` (2nd argument of `useMutation`) replaces the default
  `commitMutation` from `relay-runtime`. It has the same signature, and a test
  double or a wrapper can use it.
- `isInFlight` is `true` while any mutation that this hook committed is in
  flight. Several commits can overlap, and `isInFlight` turns `false` after the
  last one finishes. A change of `environment` or `mutation` resets it.
- On v20 the hook skips `isInFlight` state updates after the component
  unmounts. On v21 it does not guard them (`useMutation.js`, `isMountedRef`
  removed).

---

## useSubscription

Subscribes to a GraphQL subscription for the lifetime of the component.

### Signature

```ts
function useSubscription<TSubscription extends OperationType>(
  config: {
    subscription: GraphQLTaggedNode;
    variables: TSubscription['variables'];
    onNext?: (response: TSubscription['response'] | null | undefined) => void;
    onError?: (error: Error) => void;
    onCompleted?: () => void;
    updater?: SelectorStoreUpdater<TSubscription['response']>;
    cacheConfig?: CacheConfig;
  },
  requestSubscriptionFn?: (
    env: IEnvironment,
    config: GraphQLSubscriptionConfig<TSubscription>,
  ) => Disposable,
): void;
```

### Example

```tsx
import { useMemo } from 'react';
import { graphql, useSubscription } from 'react-relay';
import type { GraphQLSubscriptionConfig } from 'relay-runtime';
import type { TypingSubscription } from './__generated__/TypingSubscription.graphql';

const subscription = graphql`
  subscription TypingSubscription($roomId: ID!) {
    typingIndicator(roomId: $roomId) {
      user { id name }
      isTyping
    }
  }
`;

export function TypingIndicator({ roomId }: { roomId: string }) {
  const config = useMemo<GraphQLSubscriptionConfig<TypingSubscription>>(
    () => ({
      subscription,
      variables: { roomId },
      onNext: payload => {
        console.log('typing update', payload);
      },
      onError: err => console.error(err),
    }),
    [roomId],
  );

  useSubscription<TypingSubscription>(config);
  return null;
}
```

### Behavior

- `useSubscription` starts the subscription in an effect after the component
  commits. It never starts the subscription during render.
- The effect disposes the subscription on unmount. It disposes and restarts
  the subscription when the environment, `config` or `requestSubscriptionFn`
  changes by identity. Memoize `requestSubscriptionFn` as well as `config`.
- `requestSubscriptionFn` has the signature of `requestSubscription` and
  defaults to it. A wrapper or a test double can replace it.
- `onNext(response)` receives the subscription selection read from the store
  after the update. The read stops at fragment spreads, and `response` can be
  `null`.
- `updater` and `configs` are mutually exclusive in the config. A dev
  warning appears when both are set.
- Spread the fragments of the components that show the data into the
  subscription payload. Each event then updates those components in 1 round
  trip.

### Suspense behavior

Does not suspend. Live data flows into the store and triggers re-renders in
any component using a fragment that reads it.

### Pitfalls

- The `config` object must be memoized with `useMemo`. A new object on every
  render will unsubscribe and resubscribe constantly.
- The environment's network layer must implement `subscribe` (e.g. using
  `graphql-ws`) — otherwise this hook throws.
- For complex lifecycle control (manual start/stop, retries),
  use `requestSubscription` imperatively instead.

---

## useClientQuery

Reads a query composed exclusively of client-only fields (schema extensions).
Never hits the network.

### Signature

```ts
function useClientQuery<TQuery extends OperationType>(
  gqlQuery: GraphQLTaggedNode,
  variables: TQuery['variables'],
  options?: { UNSTABLE_renderPolicy?: 'full' | 'partial' },
): TQuery['response'];
```

Behaviorally equivalent to `useLazyLoadQuery` with
`fetchPolicy: 'store-only'`, but enforced at compile time — the query must
not reference any server fields.

### Example

```tsx
// schema.client.graphql
//   extend type Query { theme: Theme }
//   type Theme { mode: String! accent: String! }

import { graphql, useClientQuery } from 'react-relay';
import type { ThemeBadgeQuery } from './__generated__/ThemeBadgeQuery.graphql';

export function ThemeBadge() {
  const data = useClientQuery<ThemeBadgeQuery>(
    graphql`
      query ThemeBadgeQuery {
        theme {
          mode
          accent
        }
      }
    `,
    {},
  );

  if (!data.theme) return null;
  return (
    <span style={{ color: data.theme.accent }}>{data.theme.mode}</span>
  );
}
```

### Suspense behavior

Does not suspend — there is no network request. Renders synchronously from
the store.

### Pitfalls

- All fields must be declared in a client schema extension; mixing a single
  server field causes a compiler error. For mixed reads, use
  `useLazyLoadQuery` or `usePreloadedQuery`.
- Client data is not populated automatically. Seed it via
  `environment.commitPayload`, `commitLocalUpdate`, or the `updater` of a
  mutation/subscription.
- Client data is garbage-collected like any other store data if nothing
  retains it.

---

## useRelayEnvironment

Returns the `IEnvironment` provided by the nearest `RelayEnvironmentProvider`.
Use it to call imperative APIs (`commitMutation`, `fetchQuery`,
`commitLocalUpdate`) from inside a component.

### Signature

```ts
function useRelayEnvironment(): IEnvironment;
```

### Example

```tsx
import { useCallback } from 'react';
import {
  graphql,
  useRelayEnvironment,
} from 'react-relay';
import { commitLocalUpdate } from 'relay-runtime';

export function ResetThemeButton() {
  const environment = useRelayEnvironment();

  const reset = useCallback(() => {
    commitLocalUpdate(environment, store => {
      const root = store.getRoot();
      const theme = root.getLinkedRecord('theme');
      theme?.setValue('light', 'mode');
      theme?.setValue('#0066ff', 'accent');
    });
  }, [environment]);

  return <button onClick={reset}>Reset theme</button>;
}
```

### Suspense behavior

Does not suspend.

### Pitfalls

- Must be called inside a `<RelayEnvironmentProvider>`. Outside the provider,
  it throws at runtime.
- The environment reference changes only if the provider's `environment`
  prop changes. Treat it as stable for `useCallback`/`useEffect` deps.
- Prefer `useMutation` and `useSubscription` over the imperative APIs when
  possible — they handle subscription lifecycle and in-flight state for you.

---

## Fetch policy by API

| API | Accepted `fetchPolicy` | Default |
|---|---|---|
| `useLazyLoadQuery` | `store-or-network`, `store-and-network`, `network-only`, `store-only` | `store-or-network` |
| `useClientQuery` | none; the hook fixes `store-only` | `store-only` |
| `loadQuery`, `useQueryLoader` loader | `store-or-network`, `store-and-network`, `network-only`; the runtime also accepts `store-only` | `store-or-network` |
| `usePreloadedQuery` | none; it uses the policy of the ref | — |
| `refetch` of `useRefetchableFragment` and `usePaginationFragment` | `fetchPolicy` option; see "Fetch Policies" in the Relay docs | — |
| `loadNext`, `loadPrevious` | none; each call sends a network request | — |
| `fetchQuery` | `network-only`, `store-or-network` | `network-only` |

---

## Choosing the right hook

| Need | Hook |
|---|---|
| Read a fragment off a parent ref | `useFragment` |
| Fetch a query at a route boundary before render | `useQueryLoader` + `usePreloadedQuery` |
| Fetch a query lazily during render (prototypes, small apps) | `useLazyLoadQuery` |
| Refetch a fragment with new variables | `useRefetchableFragment` |
| Paginate a `@connection` | `usePaginationFragment` |
| Run a mutation with optimistic UI | `useMutation` |
| Subscribe to live data | `useSubscription` |
| Read client-only schema fields | `useClientQuery` |
| Access the environment for imperative APIs | `useRelayEnvironment` |
