---
name: react-relay
description: Use when working with Relay in a React app — writing fragments, queries, mutations, pagination, subscriptions, resolvers; debugging compiler/runtime errors; configuring caching, fetch policies, or network layer; testing Relay components. Triggers on any `useFragment`, `usePreloadedQuery`, `useMutation`, `usePaginationFragment`, `useRefetchableFragment`, `useSubscription`, `useQueryLoader`, `useEntryPointLoader`, `commitLocalUpdate`, `ConnectionHandler`, `@connection`, `@refetchable`, `@argumentDefinitions`, `@appendEdge`, `@relayField`, `@relayType`, `@RelayResolver`, `@required`, `@catch`, `@throwOnFieldError`, `@alias`, `@defer`, `@stream`, RelayEnvironmentProvider, relay-compiler error, `__generated__`, "inconsistent typename", "why is my field null".
---

# React Relay

## Mental Model

- **Fragments are the unit.** Each component declares its own data needs via a fragment. Parent queries compose children by spreading fragments.
- **Data masking.** A component can only read fields in its own fragment — never a parent's or child's. Pass the fragment ref (`$key`) down, not the data.
- **Compiler-first.** Every `graphql\`...\`` template is compiled ahead of time. Re-run `relay-compiler` after every GraphQL edit. Commit `__generated__/` to source control.
- **Normalized store.** Records are keyed by `id`. Mutating a record re-renders every subscriber across the app. The compiler adds the `id` selection for you.
- **Render-as-you-fetch.** Start the network request in an event handler / route loader, pass a query reference down, suspend on read. Prefer this over a fetch during render.

## Version check — do this first

Read the `react-relay` and `relay-compiler` versions in `package.json`. This skill describes Relay v21.0.1. The table lists the main differences in v20. Each file marks the other v21-only items (log events, CLI subcommands, type fields) at the place of use. An item without a version mark has the same docs text or the same source in v20.1 and v21.

| Item | Relay v20 | Relay v21 |
|---|---|---|
| Resolver docblock tag | `@RelayResolver TypeName` and `@RelayResolver Type.field: T`. The compiler ignores `@relayType` / `@relayField`. | `@relayType TypeName` and `@relayField Type.field: T` |
| TypeScript types | Install `@types/react-relay` and `@types/relay-runtime` | Shipped in the packages (from 21.0.1). Remove the `@types` packages. |
| `relay-compiler codemod fix-all` | Absent | Present |
| `relay-compiler --noWatchman` | Absent | Present (from 21.0.1) |
| `@required(action: DANGEROUSLY_THROW_ON_SEMANTICALLY_NULLABLE_FIELD)` | Absent | Present |
| `@catch` on a `@connection` field or a client edge field | Not supported | Supported |
| `@live_query` | Present | Removed. Use `@client_polling(interval:)` or `@live`. |
| `@oneOf` input types | Object type with all-optional fields | Union type that permits 1 property; `"oneOfType": "ignore"` restores the object type |
| `react-relay/rsc_EXPERIMENTAL` | Absent | Present, experimental |
| `usePreloadedQuery` with a null ref | Throws (the hook destructures the ref) | Returns `null` at runtime (Flow). The TypeScript type stays non-null. |
| `useMutation` after the component unmounts | Skips the `isInFlight` state update | Sets the state without a mounted check |
| `@alias` enforcement flag `enforce_fragment_alias_where_ambiguous` | `disabled` when the config has no `featureFlags` object | `enabled` by default |
| Feature flags `allow_legacy_relay_resolver_tag` and `disallow_required_action_throw_on_semantically_nullable_fields` | Absent | Present, default `disabled` |
| Environment and Store option `deferDeduplicatedFields` | Absent | Present |

The resolver examples in [resolvers.md](./resolvers.md) and [directives.md](./directives.md) use the v21 tags. On v20, write `@RelayResolver` in place of `@relayType` and `@relayField`; the rest of each docblock is the same.

## Navigation — which file to read

| Topic | File | When |
|---|---|---|
| Hook APIs, signatures, examples | [hooks.md](./hooks.md) | Writing/reading any `use*` hook |
| GraphQL directives reference | [directives.md](./directives.md) | Adding `@connection`, `@refetchable`, `@defer`, etc. |
| Mutations, connections, optimistic UI | [updating-data.md](./updating-data.md) | Writing mutations or modifying the store |
| Fetch policies, GC, staleness | [caching.md](./caching.md) | Choosing fetch policy or debugging cache behavior |
| Custom fetch, auth, subs transport, persisted queries | [network.md](./network.md) | Configuring Network layer or server integration |
| Client-side derived state, live fields | [resolvers.md](./resolvers.md) | Using `@relayField` / `@relayType` (v21) or `@RelayResolver` (v20) |
| EntryPoint APIs, code-split routing | [entrypoints.md](./entrypoints.md) | Route-level preloading |
| Imperative APIs (outside React) | [runtime.md](./runtime.md) | `fetchQuery`, `commitMutation`, `Store`, `Environment` |
| Testing components, mocking payloads | [testing.md](./testing.md) | Writing Jest/RTL tests |
| DevTools, typename error, null fields | [debugging.md](./debugging.md) | Something broke |
| Compiler/runtime architecture, mental models | [principles.md](./principles.md) | Understanding why Relay behaves as it does |
| Codemods, upgrades, migrations | [codemods.md](./codemods.md) | Upgrading Relay versions |

## Everyday Quick Reference

Each example is a trimmed copy from the Relay v21.0.1 docs (`api-reference/hooks/`). The docs write the examples in Flow. [hooks.md](./hooks.md) has the full examples.

### Read data in a component

```js
function UserComponent(props: Props) {
  const data = useFragment(
    graphql`
      fragment UserComponent_user on User {
        name
        profile_picture(scale: 2) {
          uri
        }
      }
    `,
    props.user,
  );

  return (
    <>
      <h1>{data.name}</h1>
    </>
  );
}
```

### Load a query from an event handler

```js
const AppQuery = graphql`
  query AppQuery($id: ID!) {
    user(id: $id) {
      name
    }
  }
`;

function QueryFetcherExample() {
  const [
    queryReference,
    loadQuery,
    disposeQuery,
  ] = useQueryLoader(
    AppQuery,
  );
}

function NameDisplay({ queryReference }) {
  const data = usePreloadedQuery(AppQuery, queryReference);

  return <h1>{data.user?.name}</h1>;
}
```
Render `NameDisplay` inside `<React.Suspense>` when `queryReference` is not null.

### Mutate

```js
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
```
Add item to a list → use `@appendEdge(connections: $connections)` on the mutation payload.

### Paginate and refetch

- Paginate: `usePaginationFragment`. The fragment needs `@refetchable(queryName: "...")` and `@connection(key: "...")`. Example: [hooks.md](./hooks.md).
- Refetch with new variables: `useRefetchableFragment`. Example: [hooks.md](./hooks.md).

## Decision Shortcuts

| Need | Use |
|---|---|
| Render component with data | `useFragment` |
| Fetch at route entry | `useQueryLoader` + `usePreloadedQuery` |
| Fetch a query during render | `useLazyLoadQuery` (the docs prefer `useQueryLoader` + `usePreloadedQuery`; nested lazy queries can waterfall) |
| Paginate a connection | `usePaginationFragment` |
| Paginate with a prefetched buffer (experimental) | `usePrefetchableForwardPaginationFragment` |
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
| Forgot to re-run compiler | `relay-compiler --watch` during dev (needs watchman); `relay-compiler --validate` in CI |
| Reading a field not in fragment | Add it — masking hides undeclared fields |
| `loadQuery` during render | Move to effect / event handler / router loader |
| Missing Suspense boundary | Any data hook can suspend — wrap it |
| Non-unique `@connection` key | Convention: `<fragment_name>_<field_name>`, e.g. `FriendsList_user_friends` |
| Adding item to list without `@appendEdge` or updater | Relay can't guess — use a declarative directive or manual updater |
| Using fragment ref as data | `useFragment` returns data; the ref is opaque |
| Nested `useLazyLoadQuery` | Causes waterfalls — lift to route level, use fragments below |

## Golden Rules

1. **One fragment per component that reads data.** Compose via fragment spreads.
2. **Types need a globally unique `id`.** The compiler adds the `id` selection to each type that has one. This enables normalization and mutation merging.
3. **Return modified records from mutations by `id`.** Relay auto-merges them into the store.
4. **For list changes, use `@appendEdge`/`@deleteEdge`.** Fall back to manual `updater` only when declarative can't express it.
5. **Wrap data-reading components in `<Suspense>` + error boundary.** Every hook that reads can suspend or throw.
6. **Use `useTransition` around `refetch`, `loadNext`, variable changes.** Avoids fallback flicker.

## When Something Breaks

1. Compiler error? → [debugging.md](./debugging.md) § Common compiler errors, § Stale generated artifacts
2. `Inconsistent __typename` warning? → [debugging.md](./debugging.md) § Typename
3. Field unexpectedly null? → [debugging.md](./debugging.md) § Why is my field null?
4. Mutation ran but UI didn't update? → [debugging.md](./debugging.md) + [updating-data.md](./updating-data.md) § Connections
5. Test hangs / never resolves? → [testing.md](./testing.md) § Troubleshooting
