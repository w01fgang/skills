# Principles & Architecture

Relay is a GraphQL client designed around a compile-time optimizer, a normalized runtime store, and a fragment-centric data model. This document consolidates the conceptual foundations from relay.dev into a hooks-era reference.

## 1. Thinking in GraphQL

GraphQL solves structural problems that REST cannot address cleanly once view hierarchies grow.

### 1.1 REST failure modes

| Problem | REST behavior | GraphQL behavior |
| --- | --- | --- |
| Round trips | List endpoint + N detail endpoints | Single query fetches entire tree |
| Over-fetching | Endpoint returns fixed payload | Client selects exact fields |
| Under-fetching | Client needs supplemental calls | Nested selection in one document |
| Cache staleness | URI-keyed cache with duplicated entities | Normalized cache keyed by entity id |
| Mutations | Re-fetch or guess changed data | Mutation selection set returns updated fields |

### 1.2 Waterfalls vs coalesced fetching

A naive client fetches a list, then fires one request per item to populate details. Each dependent request is a network round trip; tail latency compounds.

```
REST:  [list] --> [item1] --> [item2] --> [item3] --> render
GQL:   [one query: list { id, title, item { details } }] --> render
```

GraphQL lets clients describe the entire view's data needs as a tree. The server resolves it in one pass and returns a response shaped exactly like the query.

### 1.3 Tree-shaken responses

Because the client specifies fields, the response carries no unused bytes. Adding a new field to a component is a client-only change (given the schema already exposes it). Removing a field from a component automatically stops fetching it, because Relay's compiler re-derives the query from the fragments actually spread.

### 1.4 Co-located data requirements

Each component owns the GraphQL fragment that describes what it needs to render. The requirements travel with the component in source: when a component moves, deletes, or changes, its data requirements move with it. The compiler stitches fragments into a single operation at build time.

### 1.5 Declarative data fetching

Developers describe what data is needed, not how or when to fetch it. The framework decides the network, cache, and consistency mechanics.

## 2. Thinking in Relay

Relay takes GraphQL's structural advantages and enforces them with a component contract.

### 2.1 Fragments as the primary unit

A fragment is a named selection on a type. It is the atom of composition in Relay.

```graphql
fragment UserCard_user on User {
  id
  name
  avatarUrl
}
```

Components declare fragments; parents compose them by spreading child fragments into their own. The root query is just the outermost fragment wrapped in an operation.

### 2.2 Data masking

A component may only read fields it explicitly selects in its own fragment. If a parent fetches `email` but the child did not declare `email` in its fragment, the child cannot read it — Relay hides it.

Consequences:
- Components cannot form hidden dependencies on sibling or parent data
- Refactoring one component's fragment cannot silently break another
- Removing a component cleanly removes its fields from the generated query

### 2.3 Render-as-you-fetch (hooks)

The hooks API expresses three request shapes:

| Hook | Purpose |
| --- | --- |
| `useFragment` | Read a fragment's data for a component; subscribe to changes |
| `usePreloadedQuery` | Read a query whose fetch was started earlier (outside render) |
| `useLazyLoadQuery` | Fetch on first render; use only when preloading is impossible |
| `useQueryLoader` | Start a fetch imperatively (e.g. on route transition) |

The canonical pattern is render-as-you-fetch: kick off the query before rendering (route change, link hover, event handler) with `loadQuery`, then render a component that calls `usePreloadedQuery`. Data and code stream in parallel rather than sequentially.

```
loadQuery() -------\
                    \
route change ------> render ---> usePreloadedQuery (suspends on pending data)
                    /
code split ---------/
```

This avoids the classic React fetch-on-render waterfall.

### 2.4 Mutations as data changes

A mutation is a GraphQL operation whose selection set describes which fields may change. The server returns the new values; Relay merges them into the store; every component subscribed to those records re-renders.

- Optimistic updaters let the UI reflect the change immediately
- Updater functions let the client describe store mutations the server response cannot express (inserting into a connection, removing an item)
- Declarative directives (`@appendEdge`, `@prependEdge`, `@deleteRecord`) cover the common cases without hand-written updaters

### 2.5 Pagination via connections

Relay standardizes paginated lists through the Connection specification.

```graphql
friends(first: $count, after: $cursor) @connection(key: "User_friends") {
  edges { node { id name } }
  pageInfo { endCursor hasNextPage }
}
```

`usePaginationFragment` derives a `loadNext` / `loadPrevious` function from the `@connection` directive. The store merges new edges into the existing connection record, so the UI reads the full list from one place.

### 2.6 Component encapsulation

A parent may not read fields from a child's fragment without spreading it. A child may not read fields outside its own fragment. This symmetry keeps data ownership local and refactor-safe.

## 3. Architecture Overview

Relay is three collaborating systems:

```
+-------------+      +-------------+      +-------------+
|  Compiler   | ---> |   Runtime   | <--> |   Network   |
| (build-time)|      | (in-app)    |      | (transport) |
+-------------+      +-------------+      +-------------+
       |                    |
  reads *.{ts,tsx}     Store + RecordSource
  writes __generated__  Environment + Observables
```

### 3.1 Build pipeline

1. Compiler scans source files for `graphql\`...\`` literals
2. Parses each literal against the schema into an IR
3. Applies transforms (normalization, flattening, deduplication)
4. Emits artifacts per operation and per fragment into `__generated__`
5. Generates TypeScript/Flow types for each fragment and operation

At runtime, the tagged `graphql` template is a no-op marker; the real payload is the generated artifact imported by the hooks.

### 3.2 Store model

The store is a normalized graph of Records. A Record is `{ id, __typename, ...fields }`. References between records are stored by id, not by inlined objects. Reading a fragment walks the graph starting from a root id, following links.

## 4. Compiler Architecture

The compiler is the optimizer that makes runtime cheap.

### 4.1 Phases

```
source files
    |
    v
[ Parser ]  ---> IR (Intermediate Representation)
    |
    v
[ CompilerContext ]  (immutable: schema + name -> IR)
    |
    v
[ Transforms ]  ---> mutated CompilerContext
    |
    v
[ Codegen / Printer ]  ---> __generated__ artifacts + types
```

### 4.2 Intermediate Representation

The IR is richer than a raw GraphQL AST. Conditional branches (`@include`, `@skip`) are represented as first-class nodes, making it trivial to target them in transforms. Fragment spreads, inline fragments, and directive arguments are all normalized structures.

### 4.3 CompilerContext

An immutable snapshot of the schema plus every document in the codebase, keyed by name. Transforms are pure functions `CompilerContext -> CompilerContext`, which keeps the pipeline composable and testable.

### 4.4 Key transforms

| Transform | Purpose |
| --- | --- |
| FlattenTransform | Inlines anonymous fragments on matching parent types, reducing indirection |
| SkipRedundantNodeTransform | Removes fields fetched twice in overlapping branches |
| MaskTransform | Enforces data masking at compile time |
| ConnectionTransform | Rewrites `@connection` into the pagination machinery |
| MatchTransform | Wires up `@match` / `@module` for 3D data-driven code splitting |
| RefetchableFragmentTransform | Generates a refetch query for `@refetchable` fragments |

### 4.5 Normalization and deduplication

The compiler produces two artifacts per operation:

- Reader AST — describes how to read a fragment from the store
- Normalization AST — describes how to write a server response into the store

Deduplication ensures fields requested in multiple nested fragments resolve to one selection in the network request. The Reader preserves the per-component view; the Normalization AST preserves the single canonical write.

### 4.6 Type generation

For each fragment and operation, the compiler emits type definitions:

- `$data` — the shape a component receives from `useFragment` or `usePreloadedQuery`
- `$key` — the opaque type a parent passes to a child's `useFragment` call
- `$variables` / `Response` — types for operation inputs and outputs

Type safety follows from the generated types; there is no runtime type checking.

## 5. Runtime Architecture

The runtime executes reads, writes, subscriptions, and network requests against the normalized store.

### 5.1 Components

```
+----------------------------------------------+
|                  Environment                 |
|   +----------------+     +---------------+   |
|   |     Store      | <-> |    Network    |   |
|   |  (source of    |     |  (fetch fn)   |   |
|   |   truth)       |     +---------------+   |
|   |                |                         |
|   |  RecordSource  |                         |
|   +----------------+                         |
+----------------------------------------------+
```

| Component | Responsibility |
| --- | --- |
| `Environment` | Public API: fetch, commit, subscribe. Wraps Store + Network |
| `Store` | Holds canonical RecordSource; manages subscriptions, retention, GC |
| `RecordSource` | Keyed map of Records. Used for both the store and incoming patches |
| `Record` | `{ id, __typename, fields }`. The graph node |
| `Network` | `fetch(operation, variables, cacheConfig)` returns an Observable of payloads |

### 5.2 Data IDs

Each Record has a globally unique data id. Sources:
- The server-provided `id` field (preferred)
- A client id derived from the path (`client:root:viewer:friends(first:10)`) when `id` is absent

Relay depends on id stability for cache consistency. Two queries that return the same entity under different paths converge on the same Record.

### 5.3 Reading a fragment

```
useFragment(fragmentRef)
    |
    v
environment.lookup(selector)  --> Snapshot {
    |                              data,          // fragment $data
    v                              seenRecords,   // ids touched
environment.subscribe(snap, cb)    isMissingData, // true if store incomplete
                                   selector }
```

The Snapshot records exactly which record ids were read. Subscriptions fire only when one of those ids changes.

### 5.4 Operation lifecycle

```
fetch(operation, variables)
    |
    v
Network.execute  -->  Observable<GraphQLResponse>
    |
    v
Normalize response through Normalization AST
    |
    v
Produce RecordSource of new/updated Records
    |
    v
Store.publish(recordSource)  // merges into canonical source
    |
    v
Store.notify()  // diffs snapshots, invokes changed subscriptions
    |
    v
Components re-render with new fragment data
```

Merge semantics:
- New Records are added
- Existing Records have fields merged field-by-field
- Null fields delete the Record (for explicit server deletions)

### 5.5 Garbage collection

`environment.retain(operation)` marks an operation's root as live. When all retainers release, the Store marks the operation's reachable Records as eligible for GC. `useLazyLoadQuery` / `usePreloadedQuery` manage retention automatically for the duration the component is mounted.

### 5.6 Optimistic updates

A mutation can attach an optimistic response or an optimistic updater. The Store layers the optimistic RecordSource on top of the canonical one and notifies subscribers immediately. When the server response arrives, the optimistic layer is rolled back and the real response is normalized and published.

### 5.7 Observables and suspense

Queries return Relay Observables (similar to RxJS). Hooks wire those into React Suspense: when a fragment's data is incomplete and a fetch is in flight, the hook throws the pending promise, letting Suspense boundaries show fallbacks. Once the fetch resolves and the store publishes, the component resumes.

## 6. Why Relay vs Apollo/urql

| Dimension | Relay | Apollo Client | urql |
| --- | --- | --- | --- |
| Core unit | Fragment (compile-time) | Query / typed-document-node | Query document |
| Compiler | Required; generates artifacts + types | Optional codegen (separate tool) | Optional codegen |
| Type safety | Enforced via generated `$data` / `$key` | User opts into codegen | User opts into codegen |
| Data masking | Enforced at compile and runtime | Not enforced | Not enforced |
| Store | Normalized by id; single source | Normalized by id (InMemoryCache) | Document cache default; graphcache exchange adds normalization |
| Pagination | `@connection` spec + generated helpers | Field policies + `fetchMore` | Pagination exchange + manual merging |
| Mutations | Declarative directives + updaters; optimistic layers | `update` callback + `optimisticResponse` | Updates via graphcache updaters |
| Render model | Suspense-first, render-as-you-fetch | Hooks with loading booleans; Suspense opt-in | Hooks; Suspense opt-in |
| Fragment composition | Core workflow | Supported but not idiomatic | Supported but not idiomatic |
| Bundle cost | Higher (runtime + compiler pipeline) | Medium-large runtime | Small core, opt-in exchanges |
| Setup overhead | High (compiler, schema, artifacts in build) | Low | Very low |
| Best fit | Large apps with strict consistency and team velocity needs | Mid-size apps wanting flexibility | Small apps, custom caching strategies |

### Architectural tradeoffs

- Relay forces a build step. In return, the runtime is thin and the type system is exact.
- Relay enforces fragment composition and data masking. In return, refactors are local and safe.
- Relay standardizes pagination through connections. In return, list views are uniform across the codebase.
- Apollo and urql optimize for flexibility and quick start. Relay optimizes for correctness and scale once the team has committed to GraphQL as the data layer.

Relay is the right choice when the cost of the compiler is amortized across a large app with many components, teams, and long-lived data consistency requirements. For smaller apps or teams not ready to commit to the fragment-first workflow, Apollo or urql are lighter on ceremony.
