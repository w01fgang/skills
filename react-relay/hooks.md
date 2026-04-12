# React Relay Hooks

Complete reference for every React Relay hook. All examples are hooks-only
(no `QueryRenderer`, no `createFragmentContainer`). Types shown are the public
surface you will see in `react-relay` TypeScript definitions.

All hooks must be used inside a component tree wrapped with
`<RelayEnvironmentProvider environment={env}>`. Data-fetching hooks integrate
with React `Suspense` and React error boundaries.

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
): TQuery['response'];
```

- `gqlQuery` — the same `graphql` query tag used to create the preloaded
  reference.
- `preloadedQuery` — the `PreloadedQuery<TQuery>` returned by
  `useQueryLoader` or `loadQuery`.

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
| `UNSTABLE_renderPolicy` | `'partial'` | `'full'` suspends unless the entire query is cached. |

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
- Cannot be used below a route-level `usePreloadedQuery` without creating
  waterfalls.

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

### Suspense behavior

Suspends when the refetch is in flight and the requested data is not already
cached. Use `startTransition` to avoid flashing fallbacks and keep the old
data visible while the new data is loading.

### Pitfalls

- Missing `@refetchable` directive — compilation fails.
- Fragment must be on `Viewer`, `Query`, or a type implementing `Node`.
- Variables you omit fall back to the values from the original parent query.
- `refetch` re-renders the component; if you are not inside a transition,
  the subtree can suspend and replace the UI with the fallback.

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

### Suspense behavior

- `loadNext` and `loadPrevious` never suspend. They set
  `isLoadingNext` / `isLoadingPrevious`, then append results to the
  connection.
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
- Only pagination variables change between loads — other variables are
  locked to whatever the parent query fetched.

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
  is the `errors` array from the GraphQL response, if any.
- `onError(error)` — network or unexpected failure.
- `onUnsubscribe` — fired when the returned `Disposable` is disposed.
- `optimisticResponse` — synthetic response applied to the store immediately;
  rolled back automatically if the request errors.
- `optimisticUpdater` — imperative store mutation for cases the
  `optimisticResponse` cannot express (e.g. inserting into a connection).
- `updater` — imperative store mutation applied after the real response.
  Use for connection edits and anything not expressed by field selections.
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
