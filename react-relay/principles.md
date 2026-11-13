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

### 1.6 Response caches and consistency

Source: v21 docs `principles-and-architecture/thinking-in-graphql` (same text in v20.1.0).

- A response cache keyed by URI or by query text fails when queries overlap. A `stories` query can show `likeCount: 1` while a later `story(id: "123")` query shows `likeCount: 2`. The 2 cached responses disagree.
- Relay normalizes each response into records. The cache maps IDs to records. A record maps field names to values. A link to another record stores that record's ID. Each entity exists once, however a query fetched it.
- A field's storage key includes its arguments. `photo(size: 32)` and `photo(size: 64)` are 2 fields. Pagination needs merge logic: `stories(first: 10, offset: 10)` appends to the cached list. For this reason the cache processes the payload and the query together.
- Reading the cache walks the query like a GraphQL executor, over fixed data and without async results. Relay also runs a diff traversal that finds the missing fields. The diff shrinks the request, or removes it when the cache holds everything.
- Relay keeps a map from each view to the IDs the view read. A write notifies only the views whose IDs changed. Immutable records alone cannot do this: a change to the author record (`2`) leaves the story record (`1`) unchanged, though the story view shows the author.
- A mutation selects the fields that may change. The server cannot report all changes itself: the schema differs from the storage layout, and privacy rules decide what the viewer sees (for example `age`).

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

Fragment references enforce the contract. A fragment cannot be fetched on its own. A component gets a fragment reference by spreading its fragment into a parent fragment or a query, and every fragment ends up spread into a query. Relay checks the reference: when `<Story>` renders `<AuthorDetails>` without spreading its fragment, Relay warns, even when another component fetched the same fields. The code works today and breaks when that other component changes. All fields are nullable by default, so `data.story.author` can be `null`.

### 2.3 Render-as-you-fetch (hooks)

The hooks API has these request hooks:

| Hook | Purpose |
| --- | --- |
| `useFragment` | Read a fragment's data for a component; subscribe to changes |
| `usePreloadedQuery` | Read a query whose fetch was started earlier (outside render) |
| `useLazyLoadQuery` | Fetch on first render; the docs prefer `usePreloadedQuery` |
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

### 2.7 One request for a view hierarchy

Source: v21 docs `principles-and-architecture/thinking-in-relay` (same text in v20.1.0).

Most products want one behavior: fetch all data for a view hierarchy, show a loading indicator, then render the whole view. Two simple designs fail:

- A root component declares and fetches the data of all children. Every change to a child forces a change to every root that can render it.
- Each component fetches its own data. A component can render different children depending on its data, so a child cannot start its fetch until the parent's fetch ends. The fetches run in stages, with one slow round trip per level.

Relay lets each component declare its data and merges the declarations into one query at build time. The Relay compiler finds the requirements of the whole subtree statically, before the app runs. The runtime sends 1 network request for the entire view.

## 3. Architecture Overview

Relay has three core parts: the Relay Compiler, the Relay Runtime, and React/Relay (the hooks). The network layer is a component of the runtime. The data flow:

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

### 3.3 Module roles and loose coupling

Source: v21 docs `principles-and-architecture/architecture-overview` (same text in v20.1.0).

- The compiler is a GraphQL-to-GraphQL optimizing compiler. It transforms and optimizes queries and generates build artifacts. Custom directives are translated into standard, spec-compliant GraphQL at compile time, which makes experiments with new GraphQL features easy.
- The runtime is a high-performance GraphQL runtime for building higher-level client APIs. It provides a normalized object cache, optimized read and write operations, a generic hook for incremental field data (used by pagination), garbage collection of unreferenced entries, optimistic mutations with arbitrary logic, and primitives for subscriptions, live queries, and persisted caches.
- React/Relay is the product API. It connects the runtime to React (`useFragment` and the other hooks).
- The modules are loosely coupled. The compiler emits queries in a defined format that the runtime consumes, so the compiler is replaceable. React/Relay uses only the public runtime interface, so the runtime is replaceable and other view libraries can build on it.

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

### 4.7 Data flow and transform examples

Source: v21 docs `principles-and-architecture/compiler-architecture` (same text in v20.1.0).

The compiler extracts GraphQL text from source files and parses it with the schema into IR. The IR documents form a `CompilerContext`. Transforms rewrite the context. Then the compiler prints GraphQL (to files, or to a persisted-query store) with the `Printer` and generates artifacts with codegen. The IR encodes more GraphQL semantics than a `graphql-js` AST: `@include` and `@skip` are nodes, so a transform can merge sibling fields that share a condition and cut the number of conditionals the runtime evaluates. The `RelayCompiler` module is a helper that combines these parts for the Relay runtime. Each transform makes one kind of change; an app configures several.

`FlattenTransform` inlines an anonymous fragment whose type matches the parent type:

```graphql
# before: id is processed twice
foo { id ... on FooType { id } }
# after: id is processed once
foo { id }
```

`SkipRedundantNodeTransform` extends flattening to harder duplicates: a field that the query fetches both unconditionally and conditionally, or through 2 different sub-fragments. The result processes each field at most once.

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
- Records that are null in the published source are deleted in the store (for explicit server deletions)
- Records with a special sentinel value are removed from the store (this un-publishes optimistically created records)

`publish()` does not call subscribers. `notify()` does. The split lets several payloads publish before one round of downstream work, such as rendering. `notify()` checks each subscription in 3 steps: (1) skip it when the changed record IDs do not overlap the IDs in its last `Snapshot`; (2) re-read it and skip it when the new result equals the old one; (3) call its callback. The `Store` API details are in `runtime.md`.

### 5.5 Garbage collection

`environment.retain(operation)` marks an operation's root as live. When all retainers release, the Store marks the operation's reachable Records as eligible for GC. `useLazyLoadQuery` / `usePreloadedQuery` manage retention automatically for the duration the component is mounted.

### 5.6 Optimistic updates

A mutation can attach an optimistic response or an optimistic updater. The Store layers the optimistic RecordSource on top of the canonical one and notifies subscribers immediately. When the server response arrives, the optimistic layer is rolled back and the real response is normalized and published.

### 5.7 Observables and suspense

Queries return Relay Observables (similar to RxJS). Hooks wire those into React Suspense: when a fragment's data is incomplete and a fetch is in flight, the hook throws the pending promise, letting Suspense boundaries show fallbacks. Once the fetch resolves and the store publishes, the component resumes.

### 5.8 Selector, Snapshot, and Record access

Source: v21 docs `principles-and-architecture/runtime-architecture` (same text in v20.1.0).

- A `Selector` is a starting point for a graph traversal: a fragment, its variables, and the data ID of the root object. It selects a part of the object graph.
- A `Snapshot` is the immutable result of a selector at one point in time. It holds the selector, the data, and the list of data IDs that the read touched.
- `subscribe()` takes a `Snapshot`, not a `Selector`. With a selector alone, the store would have to re-read the data to learn which IDs to watch.
- Code reaches `Record` objects only through the `RelayModernRecord` module. Do not assume a record is a plain object; the representation can change in one place.
- `RecordSource` serves two roles: the store's record cache, and a patch that the runtime publishes to the store. The only implementation is the in-memory source; the interface also defines async record loading for future offline use.
- A client ID derives from the path to the record from the nearest parent that has an `id`, for example `client:842472:address` for the `address` field of record `842472`.

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
