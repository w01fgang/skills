# Principles & Architecture

This document consolidates the `principles-and-architecture` pages of relay.dev.

## 1. Thinking in GraphQL

### 1.1 Fetching data

A REST client that fetches a list of stories and the details of each story needs _n+1_ requests to the server: 1 to fetch the list, and _n_ to fetch each item.

```javascript
// Fetch the list of story IDs but not their details:
rest.get('/stories').then(stories =>
  // This resolves to a list of items with linked resources:
  // `[ { href: "http://.../story/1" }, ... ]`
  Promise.all(stories.map(story =>
    rest.get(story.href) // Follow the links
  ))
).then(stories => {
  // This resolves to a list of story items:
  // `[ { id: "...", text: "..." } ]`
  console.log(stories);
});
```

GraphQL fetches the same data in a single network request, without a custom endpoint:

```javascript
graphql.get(`query { stories { id, text } }`).then(
  stories => {
    // A list of story items:
    // `[ { id: "...", text: "..." } ]`
    console.log(stories);
  }
);
```

- All data is fetched in a single round trip.
- The client and server are decoupled: the client specifies the data needed.

### 1.2 Declarative data fetching

Relay is a framework for declarative data-fetching. It separates what data to fetch from how the data is fetched.

### 1.3 Response caches and consistency

Source: v21 docs `principles-and-architecture/thinking-in-graphql` (same text in v20.1.0).

- A response cache keyed by URI or by query text fails when queries overlap. A `stories` query can show `likeCount: 1` while a later `story(id: "123")` query shows `likeCount: 2`. The 2 cached responses disagree.
- Relay normalizes each response into records. The cache maps IDs to records. A record maps field names to values. A link to another record stores that record's ID. Each entity exists once, however a query fetched it.
- A field's storage key includes its arguments. `photo(size: 32)` and `photo(size: 64)` are 2 fields. Pagination needs merge logic: `stories(first: 10, offset: 10)` appends to the cached list. For this reason the cache processes the payload and the query together.
- Reading the cache walks the query like a GraphQL executor, over fixed data and without async results. Relay also runs a diff traversal that finds the missing fields. The diff shrinks the request, or removes it when the cache holds everything.
- Relay keeps a map from each view to the IDs the view read. A write notifies only the views whose IDs changed. Immutable records alone cannot do this: a change to the author record (`2`) leaves the story record (`1`) unchanged, though the story view shows the author.
- A mutation selects the fields that may change. The server cannot report all changes itself: the schema differs from the storage layout, and privacy rules decide what the viewer sees (for example `age`).

## 2. Thinking in Relay

### 2.1 Fragments as the primary unit

Fragments are named snippets of GraphQL that specify which fields to select from an object of a particular type. A component declares its data requirements with a fragment. Fragments nest within other fragments, and ultimately within queries.

```javascript
// AuthorDetails.react.js
const authorDetailsFragment = graphql`
  fragment AuthorDetails_author on Author {
    name
    photo {
      url
    }
  }
`;
```

A fragment reference is the second parameter of `useFragment`. A component gets a fragment reference by spreading its fragment into another fragment or a query. Fragments cannot be fetched directly: every fragment must be spread, directly or transitively, into a query.

### 2.2 Data masking

Relay only allows components to access data they specifically ask for in GraphQL fragments. If one component queries for the `title` of a Story and another for its `text`, each sees only the field it asked for. Components cannot see the data requested by their children.

Consequences:
- Components cannot form implicit dependencies on data that another component fetches
- Removing the data-fetching logic of one component cannot break another component

Fragment references enforce the contract. Relay checks the reference: when `<Story>` renders `<AuthorDetails>` without spreading its fragment, Relay warns, even when another component fetched the same fields. The code works today and breaks when that other component changes. All fields are nullable by default, so `data.story.author` can be `null`.

### 2.3 Render-as-you-fetch (hooks)

| Hook | Purpose |
| --- | --- |
| `useFragment` | Read a fragment's data for a component |
| `usePreloadedQuery` | Read a query whose fetch an earlier `loadQuery` call or `useQueryLoader` started |
| `useLazyLoadQuery` | Fetch a query during render; the docs prefer `usePreloadedQuery` |
| `useQueryLoader` | Load and retain queries; keeps a query reference in state |

`usePreloadedQuery` implements the "render-as-you-fetch" pattern:

- Call the `loadQuery` callback returned from `useQueryLoader`. This stores a query reference in React state.
- In the render method, consume the query reference with `usePreloadedQuery()`. The call suspends if the query is pending, throws an error if the query failed, and otherwise returns the query results.
- The docs encourage this pattern over `useLazyLoadQuery()`: it fetches data earlier and does not block rendering.

### 2.4 Mutations as data changes

A mutation queries for the data that may have changed. When the response includes an object with an `id` field and the store holds a record with a matching `id`, Relay merges the fields of the response into the existing record. Components that use a changed value re-render.

- Optimistic updates reflect the change in the UI before the server responds
- The `updater` function of `UseMutationConfig` gives full control over how to update the store
- Declarative directives (`@appendEdge`, `@prependEdge`, `@deleteRecord`) cover common cases without a hand-written updater

### 2.5 Pagination via connections

A fragment that queries for a connection marks the field with the `@connection` directive and a static unique `key`:

```javascript
const userFragment = graphql`
  fragment UserFragment on User {
    name
    friends(after: $cursor, first: $count)
      @connection(key: "UserFragment_friends") {
      edges {
        node {
          ...FriendComponent
        }
      }
    }
  }
`;
```

The docs recommend the key naming convention `<fragment_name>_<field_name>`. `usePaginationFragment` renders the fragment and returns `loadNext` to fetch more items in the connection.

### 2.6 One request for a view hierarchy

Source: v21 docs `principles-and-architecture/thinking-in-relay` (same text in v20.1.0).

Most products want one behavior: fetch all data for a view hierarchy, show a loading indicator, then render the whole view. Two simple designs fail:

- A root component declares and fetches the data of all children. Every change to a child forces a change to every root that can render it.
- Each component fetches its own data. A component can render different children depending on its data, so a child cannot start its fetch until the parent's fetch ends. The fetches run in stages, with one slow round trip per level.

Relay lets each component declare its data and merges the declarations into one query at build time. The Relay compiler finds the requirements of the whole subtree statically, before the app runs. The runtime sends 1 network request for the entire view.

## 3. Architecture Overview

Source: v21 docs `principles-and-architecture/architecture-overview` (same text in v20.1.0).

Relay has three core parts: the Relay Compiler, the Relay Runtime, and React/Relay.

- The compiler is a GraphQL-to-GraphQL optimizing compiler. It transforms and optimizes queries and generates build artifacts. Custom directives are translated into standard, spec-compliant GraphQL at compile time, which makes experiments with new GraphQL features easy.
- The runtime is a high-performance GraphQL runtime for building higher-level client APIs. It provides a normalized object cache, optimized read and write operations, a generic hook for incremental field data (used by pagination), garbage collection of unreferenced entries, optimistic mutations with arbitrary logic, and primitives for subscriptions, live queries, and persisted caches.
- React/Relay is the product API. It connects the runtime to React (`useFragment` and the other hooks).
- The modules are loosely coupled. The compiler emits queries in a defined format that the runtime consumes, so the compiler is replaceable. React/Relay uses only the public runtime interface, so the runtime is replaceable and other view libraries can build on it.

## 4. Compiler Architecture

### 4.1 Data flow and modules

Source: v21 docs `principles-and-architecture/compiler-architecture` (same text in v20.1.0).

```
                   ┌─────────────┐┌─────────────┐
                   │   GraphQL   ││   Schema    │
                   └─────────────┘└─────────────┘
                          │              │              parse
                          └───────┬──────┘
                                  ▼
                   ┌────────────────────────────┐
                   │      CompilerContext       │
                   │                            │
                   │   ┌─────┐ ┌─────┐ ┌─────┐  │──┐
                   │   │ IR  │ │ IR  │ │ ... │  │  │
                   │   └─────┘ └─────┘ └─────┘  │  │
                   └────────────────────────────┘  │  transform/
                          │    │      ▲            │   optimize
                          │    │      └────────────┘
                          │    │
                          │    └──────────┐
                          │  print        │  codegen
                          ▼               ▼
                   ┌─────────────┐ ┌─────────────┐
                   │   GraphQL   │ │  Artifacts  │
                   └─────────────┘ └─────────────┘
```

The compiler extracts GraphQL text from source files and parses it with the schema into IR. The IR documents form a `CompilerContext`. Transforms rewrite the context. Then the compiler prints GraphQL (to files, or to a persisted-query store) with the `Printer` and generates artifacts with codegen. The IR encodes more GraphQL semantics than a `graphql-js` AST: `@include` and `@skip` are nodes, so a transform can merge sibling fields that share a condition and cut the number of conditionals the runtime evaluates. The `RelayCompiler` module is a helper that combines these parts for the Relay runtime. Each transform makes one kind of change; an app configures several.

`CompilerContext` is an immutable representation of a corpus of GraphQL documents. It contains the schema and a mapping of document names to IR. A `Transform` is a function that accepts a `CompilerContext` and returns a new, modified context.

### 4.2 Transforms

`FlattenTransform` inlines an anonymous fragment whose type matches the parent type:

```
# before: `id` is processed twice
foo { # type FooType
   id
   ... on FooType { # matches the parent type, so this is extraneous
     id
   }
 }

 # after: `id` is processed once
 foo {
   id
 }
```

`SkipRedundantNodeTransform` extends flattening to harder duplicates: a field that the query fetches both unconditionally and conditionally, or through 2 different sub-fragments. The result processes each field at most once.

### 4.3 Reader AST and Normalization AST

Source: v21 docs `glossary/glossary`.

- A reader AST reads the data selected in a given fragment. Operations and fragments both have reader ASTs. A reader AST records which fragments are spread at a location, and does not include the fields selected within these fragments.
- A normalization AST belongs to an operation. With variables, it writes a network payload to the store, writes an optimistic response to the store, determines whether a query can be fulfilled from data in the store, and determines which records in the store are reachable (used in garbage collection). It includes the contents of nested fragments.
- The generated artifact of an operation (for example `FooQuery.graphql.js`) contains both a normalization AST and a reader AST.

### 4.4 Type generation

Source: v21 docs `guided-tour/rendering/fragments`.

The generated Flow types include a type for the fragment reference, with the `$key` suffix (`<fragment_name>$key`), and a type for the shape of the data, with the `$data` suffix (`<fragment_name>$data`).

## 5. Runtime Architecture

Source: v21 docs `principles-and-architecture/runtime-architecture`.

### 5.1 Data types

- `DataID`: a globally unique or client-generated identifier for a record, stored as a string.
- `Record`: a representation of a distinct data entity with an identity, type, and fields.
- `RecordSource`: a collection of records keyed by their data ID. It represents both the cache and updates to it.
- `Store`: the source of truth for an instance of `RelayRuntime`. It holds the canonical set of records as a `RecordSource`.
- `Network`: provides methods for fetching query data from and executing mutations against an external data source.
- `Environment`: an encapsulated environment that combines a `Store` and a `Network`. It is the main public API of `RelayRuntime`.

### 5.2 Data IDs

The data ID is the unique (with respect to the cache) identifier for a record. It is the value of an actual `id` field, or it derives from the path to the record from the nearest object with an `id`. Path-based IDs are client IDs, for example `client:842472:address`.

### 5.3 Reading a fragment

Products access the store primarily via `lookup()` and `subscribe()`. `lookup()` reads the initial results of a fragment, and `subscribe()` observes that result for changes. The output of `lookup()`, a `Snapshot`, is the input to `subscribe()`. Higher-level APIs such as React/Relay manage this flow automatically.

### 5.4 Operation lifecycle

```
               ┌───────────────────────┐
               │         Query         │
               └───────────────────────┘
                           │
                           ▼
                                             ┌ ─ ─ ─ ┐
                         fetch ◀────────────▶ Server
                                             └ ─ ─ ─ ┘
                           │
                     ┌─────┴───────┐
                     ▼             ▼
               ┌──────────┐  ┌──────────┐
               │  Query   │  │ Response │
               └──────────┘  └──────────┘
                     │             │
                     └─────┬───────┘
                           │
                           ▼
                       normalize
                           │
                           ▼
               ┌───────────────────────┐
               │     RecordSource      │
               │                       │
               │┌──────┐┌──────┐┌─────┐│
               ││Record││Record││ ... ││
               │└──────┘└──────┘└─────┘│
               └───────────────────────┘
```

The runtime fetches the query from the network, then traverses the query and the response together. It extracts the results into `Record` objects in a fresh `RecordSource`, then publishes that source to the store.

Merge semantics:
- Records that exist only in the published source are added to the store
- Records that exist in both are merged into a new record (inputs unchanged)
- Records that are null in the published source are deleted (set to null) in the store
- Records with a special sentinel value are removed from the store (this un-publishes optimistically created records)

`publish()` does not call subscribers. `notify()` does. The split lets several payloads publish before one round of downstream work, such as rendering. `notify()` checks each subscription in 3 steps: (1) skip it when the changed record IDs do not overlap the IDs in its last `Snapshot`; (2) re-read it and skip it when the new result equals the old one; (3) call its callback. The `Store` API details are in `runtime.md`.

### 5.5 Garbage collection

Relay runs garbage collection on the local in-memory store. It deletes data that no component in the app references. Query components that use `useQueryLoader` / `usePreloadedQuery` retain the query while they are mounted, and release it on unmount. `environment.retain()` retains a query outside of the component lifecycle.

### 5.6 Optimistic updates

A mutation can attach an optimistic response or an optimistic updater. Relay rolls back the optimistic response when the mutation succeeds or errors.

### 5.7 Suspense

`usePreloadedQuery` suspends when the query is pending.

### 5.8 Selector, Snapshot, and Record access

Source: v21 docs `principles-and-architecture/runtime-architecture` (same text in v20.1.0).

- A `Selector` is a starting point for a graph traversal: a fragment, its variables, and the data ID of the root object. It selects a part of the object graph.
- A `Snapshot` is the immutable result of a selector at one point in time. It holds the selector, the data, and the list of data IDs that the read touched.
- `subscribe()` takes a `Snapshot`, not a `Selector`. With a selector alone, the store would have to re-read the data to learn which IDs to watch.
- Code reaches `Record` objects only through the `RelayModernRecord` module. Do not assume a record is a plain object; the representation can change in one place.
- `RecordSource` serves two roles: the store's record cache, and a patch that the runtime publishes to the store. The only implementation is the in-memory source; the interface also defines async record loading for future offline use.
- A client ID derives from the path to the record from the nearest parent that has an `id`, for example `client:842472:address` for the `address` field of record `842472`.
