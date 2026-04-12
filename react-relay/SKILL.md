---
name: react-relay
description: Use when working with Relay in a React app — writing fragments, queries, mutations, pagination, subscriptions, resolvers; debugging compiler/runtime errors; configuring caching, fetch policies, or network layer; testing Relay components. Triggers on any `useFragment`, `usePreloadedQuery`, `useMutation`, `usePaginationFragment`, `useRefetchableFragment`, `useSubscription`, `useQueryLoader`, `useEntryPointLoader`, `commitLocalUpdate`, `ConnectionHandler`, `@connection`, `@refetchable`, `@argumentDefinitions`, `@appendEdge`, `@RelayResolver`, `@required`, `@defer`, `@stream`, RelayEnvironmentProvider, relay-compiler error, `__generated__`, "inconsistent typename", "why is my field null".
---

# React Relay

## Mental Model

- **Fragments are the unit.** Each component declares its own data needs via a fragment. Parent queries compose children by spreading fragments.
- **Data masking.** A component can only read fields in its own fragment — never a parent's or child's. Pass the fragment ref (`$key`) down, not the data.
- **Compiler-first.** Every `graphql\`...\`` template is compiled ahead of time. Re-run `relay-compiler` after every GraphQL edit. Commit `__generated__/` to source control.
- **Normalized store.** Records are keyed by `id`. Mutating a record re-renders every subscriber across the app. Always include `id` in fragments.
- **Render-as-you-fetch.** Start the network request in an event handler / route loader, pass a query reference down, suspend on read. Never fetch during render for critical data.

## Navigation — which file to read

| Topic | File | When |
|---|---|---|
| Hook APIs, signatures, examples | [hooks.md](./hooks.md) | Writing/reading any `use*` hook |
| GraphQL directives reference | [directives.md](./directives.md) | Adding `@connection`, `@refetchable`, `@defer`, etc. |
| Mutations, connections, optimistic UI | [updating-data.md](./updating-data.md) | Writing mutations or modifying the store |
| Fetch policies, GC, staleness | [caching.md](./caching.md) | Choosing fetch policy or debugging cache behavior |
| Custom fetch, auth, subs transport, persisted queries | [network.md](./network.md) | Configuring Network layer or server integration |
| Client-side derived state, live fields | [resolvers.md](./resolvers.md) | Using `@RelayResolver` |
| EntryPoint APIs, code-split routing | [entrypoints.md](./entrypoints.md) | Route-level preloading |
| Imperative APIs (outside React) | [runtime.md](./runtime.md) | `fetchQuery`, `commitMutation`, `Store`, `Environment` |
| Testing components, mocking payloads | [testing.md](./testing.md) | Writing Jest/RTL tests |
| DevTools, typename error, null fields | [debugging.md](./debugging.md) | Something broke |
| Compiler/runtime architecture, mental models | [principles.md](./principles.md) | Understanding why Relay behaves as it does |
| Codemods, upgrades, migrations | [codemods.md](./codemods.md) | Upgrading Relay versions |

## Everyday Quick Reference

### Read data in a component

```tsx
import { graphql, useFragment } from 'react-relay';
import type { UserCard_user$key } from './__generated__/UserCard_user.graphql';

function UserCard({ user }: { user: UserCard_user$key }) {
  const data = useFragment(
    graphql`fragment UserCard_user on User { id name avatarUrl }`,
    user,
  );
  return <div>{data.name}</div>;
}
```

### Load a query at route level

```tsx
const [queryRef, loadQuery] = useQueryLoader(HomeQuery);
useEffect(() => { loadQuery({ id: '4' }); }, []);
// below: <Suspense><Home queryRef={queryRef} /></Suspense>

function Home({ queryRef }) {
  const data = usePreloadedQuery(HomeQuery, queryRef);
  return <UserCard user={data.user} />;
}
```

### Paginate

```tsx
const { data, loadNext, hasNext, isLoadingNext } = usePaginationFragment(fragment, ref);
<button onClick={() => loadNext(20)} disabled={!hasNext || isLoadingNext}>Load more</button>
```
Fragment must use `@refetchable(queryName: "...")` + `@connection(key: "unique")`.

### Mutate

```tsx
const [commit, isInFlight] = useMutation<LikeMutation>(graphql`
  mutation LikeMutation($id: ID!) {
    likePost(id: $id) { post { id likeCount viewerHasLiked } }
  }
`);
commit({
  variables: { id: post.id },
  optimisticResponse: {
    likePost: {
      post: { id: post.id, likeCount: post.likeCount + 1, viewerHasLiked: true },
    },
  },
});
```
Add item to a list → use `@appendEdge(connections: $connections)` on the mutation payload.

### Refetch with new variables

```tsx
const [data, refetch] = useRefetchableFragment(
  graphql`
    fragment Comments_story on Story
    @refetchable(queryName: "CommentsRefetchQuery")
    @argumentDefinitions(sort: { type: "Sort", defaultValue: NEWEST }) {
      comments(sort: $sort) { edges { node { body } } }
    }
  `,
  storyRef,
);
refetch({ sort: 'OLDEST' }, { fetchPolicy: 'network-only' });
```

## Decision Shortcuts

| Need | Use |
|---|---|
| Render component with data | `useFragment` |
| Fetch at route entry | `useQueryLoader` + `usePreloadedQuery` |
| Fetch inside a leaf component | `useLazyLoadQuery` (only at route level; never nest) |
| Paginate a connection | `usePaginationFragment` |
| Change variables on the same component | `useRefetchableFragment` |
| Send a mutation | `useMutation` |
| Real-time updates | `useSubscription` |
| Preload query + code split | EntryPoint APIs ([entrypoints.md](./entrypoints.md)) |
| Add to a list | `@appendEdge` / `@prependEdge` on mutation payload |
| Remove from a list | `@deleteEdge` / `@deleteRecord` |
| Derived/computed client state | Relay Resolver ([resolvers.md](./resolvers.md)) |
| Outside React | `fetchQuery`, `commitMutation` ([runtime.md](./runtime.md)) |

## Universal Pitfalls

| Mistake | Fix |
|---|---|
| Forgot to re-run compiler | `relay-compiler --watch` during dev |
| Reading a field not in fragment | Add it — masking hides undeclared fields |
| `loadQuery` during render | Move to effect / event handler / router loader |
| Missing Suspense boundary | Any data hook can suspend — wrap it |
| Non-unique `@connection` key | Convention: `ComponentName_typeName_fieldName` |
| Adding item to list without `@appendEdge` or updater | Relay can't guess — use a declarative directive or manual updater |
| Using fragment ref as data | `useFragment` returns data; the ref is opaque |
| Nested `useLazyLoadQuery` | Causes waterfalls — lift to route level, use fragments below |

## Golden Rules

1. **One fragment per component that reads data.** Compose via fragment spreads.
2. **Always include `id` in fragments on Node types.** Enables normalization and mutation merging.
3. **Return modified records from mutations by `id`.** Relay auto-merges them into the store.
4. **For list changes, use `@appendEdge`/`@deleteEdge`.** Fall back to manual `updater` only when declarative can't express it.
5. **Wrap data-reading components in `<Suspense>` + error boundary.** Every hook that reads can suspend or throw.
6. **Use `useTransition` around `refetch`, `loadNext`, variable changes.** Avoids fallback flicker.

## When Something Breaks

1. Compiler error? → [debugging.md](./debugging.md) § Compiler errors
2. `Inconsistent __typename` warning? → [debugging.md](./debugging.md) § Typename
3. Field unexpectedly null? → [debugging.md](./debugging.md) § Why is my field null?
4. Mutation ran but UI didn't update? → [debugging.md](./debugging.md) + [updating-data.md](./updating-data.md) § Connections
5. Test hangs / never resolves? → [testing.md](./testing.md) § Troubleshooting
