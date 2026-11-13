# Debugging Relay

Reference for diagnosing Relay issues: DevTools, store consistency, mutation directives, null fields, compiler tooling and field-level error logging.

## Relay DevTools

### Installation

Install the extension from the [Chrome store](https://chrome.google.com/webstore/detail/relay-developer-tools/ncedobpgnmkhcmnnkcimnobpfepidadl). A new tab called Relay appears in your Chrome DevTools. In this tab, you select between 2 panels: the network panel and the store panel.

### Network panel

The network panel shows individual requests in an active environment. You scroll through the requests, search for requests and view the details of each request. The details of each request include the status, the variables and the responses.

### Store panel

The store panel shows individual records from the store data in an active environment. You scroll through the records, search for records and view the details of each record. The details of each record include the ID, the typename and all of the data in the record. If a field in the data is a reference to another record, click the reference to go to that record. You can copy the store data in JSON format to the clipboard.

### Multiple environments

A dropdown menu on the left side of the developer tools switches between environments. The requests in the network panel and the store data are grouped by environment.

---

## Inconsistent Typename Error

The GraphQL server likely violated the globally unique ID requirement by returning the same ID for different objects.

### Symptom

```
`RelayResponseNormalizer: Invalid record '543'. Expected __typename to be consistent, but the record was assigned conflicting types Foo and Bar. The GraphQL server likely violated the globally unique ID requirement by returning the same ID for different objects.`
```

The server implementation of one of the types is not spec compliant. Relay requires the `id` field to be globally unique. Relay stores objects in a normalized key-value store, and one of the objects overwrote the other. This breaks your app in some subtle or less subtle way.

### Common cause

The most common reason is that 2 objects backed by an ID use the plain ID as the id field, such as a `User` and a `MessagingParticipant`. Less common reasons are array indices, or auto-increment IDs from a database that are not unique to the type.

### Fix: make your type spec compliant

For 2 different types backed by the same ID, a common solution is to prefix the ID of the less widely used type with a unique string and then base64 encode the result. Implement a `NodeTokenResolver` with the helper trait `NodeTokenResolverWithPrefix`. When the `NodeTokenResolver` is registered, you can load your type with the `node(id: $yourID)` GraphQL call, and your type can return an encoded ID.

The `getDataID` option of the `Environment` is a function that generates a unique ID for a given object. It is meant for servers that do not implement the Global Object Identification spec.

---

## Debugging Declarative Mutation Directives

If you see an error similar to:

```
RelayFBHandlerProvider: No handler defined for `deleteRecord`. [Caught in: An uncaught error was thrown inside `RelayObservable`.]
```

or

```
RelayModernEnvironment: Expected a handler to be provided for handle `deleteRecord`.
```

A `handlerProvider` is passed to your Relay environment, and the handler provider does not accept the handles `"deleteRecord"`, `"appendEdge"` or `"prependEdge"`. Return `MutationHandlers.DeleteRecordHandler`, `MutationHandlers.AppendEdgeHandler` or `MutationHandlers.PrependEdgeHandler` respectively. Import them from `relay-runtime`.

---

## Why is my field null?

Several reasons can make a field read by Relay null. Some are obscure.

### 1. Server returned null

The server returned an explicit null. This happens in 2 cases:

1. The field resolver of the server returned an explicit null.
2. The field resolver throws. GraphQL then returns null for that field, even if the return type of the server resolver is non-nullable. The exception is fields annotated as non-null: the server never returns null for them. If an exception occurs, the entire parent object is nulled out.

How to tell: inspect the response of the server with Relay DevTools or the network tab of your browser dev tools, and check whether the field is null.

### 2. Graph relationship change

If a different query, mutation or subscription observes a relationship change in the graph, you can read fields off an object that your query never fetched.

A query that reads the name of your best friend:

```graphql
query MyQuery {
  me {
    best_friend {
      # id: 1
      name
    }
  }
}
```

After the query response, your best friend changes on the server. A different query, mutation or subscription fetches a different set of fields off `best_friend`:

```graphql
query OtherQuery {
  me {
    best_friend {
      # new id: 2
      # Note: name is not fetched here
      age
    }
  }
}
```

The store is normalized. Relay updates the `me` record so that the `best_friend` linked field points to the user with ID 2. The only information Relay has about that user is the age. `MyQuery` rerenders, and Relay cannot find the `name` of the user with ID 2. A relationship "change" can also be a new relationship: you start with no best friend, and a later response returns a best friend without all the fields your component needs.

Relay could refetch your query in this state. Some queries are not safe to re-issue arbitrarily, and a UI state change that is not tied to a direct user action can lead to confusion. For this reason Relay does not refetch in this scenario.

How to tell: place a breakpoint or `console.log` at the final return statement of `readWithIdentifier` in `FragmentResource`. At this point Relay knows that it is missing data and no query is in flight to get it.

### 3. Inconsistent server response

This is a rare edge case. If the server does not implement the [field stability](https://graphql.org/learn/global-object-identification/#field-stability) semantics of the id field, a field can be present in one part of the response and explicitly null in another:

```graphql
{
  me {
    id: 1
    name: "Alice"
  }
  me_elsewhere_in_the_graph {
    id: 1 # Note this is the same as the `me` field above...
    name: null
  }
}
```

Relay first learns that the `name` of user 1 is Alice, and later finds that it is `null`. User 1 can have only one value for `name` in the normalized store, so Relay ends with `name` as `null`.

How to tell: Relay detects this case and logs an error to the console in dev.

You can also inspect the query response manually.

If the unstable field is a linked field (an edge to another object), this bug can cause a Graph Relationship Change within a single response. For example, a user with the same `id` appears in two places in the response, and their `best_friend` is different in those two places. Relay shows a similar console warning in dev.

### 4. Client-side deletion or incomplete update

Imperative store updates or optimistic updates can delete a record or field. An imperative or optimistic update that writes a new record to the store may not supply a value for a field you expect to read. An updater cannot statically know all the data that is accessed off a new object.

How to tell: because of React and Relay batching, you cannot always associate a component update with the store update that triggered it. Set a breakpoint in your component for when your value is null, and use the Relay DevTools to look at the last few updates.

This can happen for a newly created object that did not supply a specific field, or for an update that causes a new or changed relationship in the graph. In the second case, use the "How to tell" tip of the Graph Relationship Change section.

---

## Stale generated artifacts

Relay depends on ahead-of-time compilation of GraphQL queries and fragments to generate artifacts. The compiler generates TypeScript/Flow types and additional JavaScript code that Relay's Babel plugin includes in your code.

If the artifacts are out of date, pass `--validate` to the compiler. It checks whether any generated artifacts are out of date without writing anything to disk. The compiler exits with a non-zero code if any artifact needs an update. This is useful in CI to assert that generated files are committed and current:

```sh
relay-compiler --validate
```

---

## Common compiler errors

### Disallowed `id` type

```
Disallowed type `String` of field `id` on parent type `Foo` cannot be used by Relay to identify entities
```

The GraphQL schema defines an object with a field named `id` that has no valid type. Valid types for this field are `ID` or `ID!` unless configured otherwise. The Relay compiler and runtime mishandle such a field and cause refresh or data updating issues. Components can fail to re-render on re-fetched data.

Relay uses Object Identification to know which GraphQL objects to refetch. These objects usually implement the `Node` interface and come with an `id` field of type `ID`. By default, Relay does not restrict object definitions, so `id` fields with non-`ID` types (for example `String`) can be defined. The runtime and compiler handle only `id` fields as the `Node` interface defines them.

Fix, with 2 recommended courses of action:

- Type all fields named `id` with `ID`.
- Rename any field named `id` (with a type that is not `ID`) to a different name, for example `special_purpose_id`.

If your application requires the `id` field definition to stay as is, add your GraphQL type and the type of its `id` field to the allowlist in `nonNodeIdFields` of the Relay Compiler's configuration. This bypasses the error only for that combination of object type and `id` field type.

---

## Field-level error logging

The `log` option of `Environment` is a function that Relay calls with telemetry events. The `LogEvent` type lists the events.

These `LogEvent` events exist in v21 only (absent in v20.1):

- `suspense.resolver`, `suspense.client_edge`, `suspense.missing_data`
- `reader.fragmentSpread`, `reader.read`, `fetchquery.fetch`
- `store.datachecker.missing`, `store.batch.start`, `store.batch.complete`

### `relayFieldLogger`

Relay features such as `@required`, `@catch`, `@throwOnFieldError` and Relay Resolvers handle field errors. To track and monitor these errors, configure the Relay Environment with a `relayFieldLogger`. The logger is a function that Relay calls with an event each time it handles a field-level error.

```ts
import {Environment} from "relay-runtime";

const environment = new Environment({
    relayFieldLogger: (event) => {
        switch(event.kind) {
            case "missing_expected_data.log":
                // ...
                break;
            // ... handle other events
        }
    },
    network: // ...
    store: // ...
});
```

The logger receives 6 event kinds. `owner` is the name of the operation or fragment. `fieldPath` is the `.` separated path from its root to the field.

| `event.kind` | When it fires |
|---|---|
| `missing_expected_data.log` | The store lacks data that the parent query, mutation or subscription requested. Graph relationship changes or imperative updates that do not provide all needed data cause this. Relay renders the field as `undefined`. |
| `missing_expected_data.throw` | The same, in a query, fragment or mutation with `@throwOnFieldError`. Relay throws after the logger returns. |
| `missing_required_field.log` | A `@required(action: LOG)` field is null or missing in the store. |
| `missing_required_field.throw` | A `@required(action: THROW)` field is null or missing in the store. Relay throws after the logger returns. |
| `relay_resolver.error` | A Relay Resolver threw a JavaScript error when it was last evaluated. By default Relay coerces the value to null. |
| `relay_field_payload.error` | The GraphQL response marks a field being read as in an error state. |

The `.throw`, `relay_resolver.error` and `relay_field_payload.error` events carry `handled`. Throw a custom error from the logger only when `handled` is `false`. A `@catch` directive or a null resolver result sets `handled` to `true`.

---

## Compiler Tooling Reference

### Config file locations

The compiler looks for a Relay config in these locations (v20.1 and v21.0.1 docs):

1. `relay.config.json` in the project root
2. `relay.config.(js|mjs|ts)` in the project root
3. A `"relay"` key in `package.json`

Pass a config file path as the positional `[CONFIG]` argument.

### Compiler CLI flags

| Flag | v20.1.1 | v21.0.1 | Effect |
|---|---|---|---|
| `--watch` | yes | yes | Recompile on change. Needs watchman. |
| `--project`, `-p` | yes | yes | Compile only this project. Repeat for several. |
| `--validate` | yes | yes | Exit non-zero when artifacts are out of date. Write nothing. |
| `--noWatchman` | absent | yes | Use directory traversal and skip watchman. The v21 docs write `--no-watchman`; the clap definition uses camel case, so the source name is `--noWatchman`. The env variable `FORCE_NO_WATCHMAN` has the same effect on both versions. |
| `codemod <cmd>` | yes (2 commands) | yes (3 commands) | `fix-all` is absent on v20.1.1. |
| `experimental-compare-document-ir` | absent | yes | Compare the IR of two documents. Experimental. |

`relay-compiler --help` and `relay-compiler <subcommand> --help` print the full command-line reference.

### Document comparison (v21 only, experimental)

`relay-compiler experimental-compare-document-ir --left <doc> --right <doc> --schemaPaths <schema>...` checks that every selection of `--left` exists in `--right`. Each document holds exactly 1 operation. The compiler inlines fragments, de-aliases fields, deduplicates fields, and treats `user(id: $id)` as a superset of `user(id: 100)`. The output lists the missing selections with line numbers and paths, for example `* query -> viewer -> timezone_estimate -> gmt_offset`. Pass the expected document via `--right` and the generated document via `--left` to find extra selections (over-fetching).

### Codemods

`relay-compiler codemod <name>` runs one of: `mark-dangerous-conditional-fragment-spreads` (option `-r`/`--rollout-percentage`), `remove-unnecessary-required-directives` and `fix-all` (v21 only). `fix-all` runs all Relay compiler transforms and applies fixes for every fixable diagnostic. Run it after you update the Relay version.

### VS Code extension and LSP

The [Relay VS Code extension](https://marketplace.visualstudio.com/items?itemName=meta.relay) uses the Language Server Protocol of the Relay compiler. It surfaces compiler errors as editor problems, often with suggested quick fixes. It provides autocomplete in `graphql` tagged template literals, hover information about Relay-specific features, strikethrough rendering of `@deprecated` fields, and click-to-definition for fragments, fields and types.

### ESLint plugin (`eslint-plugin-relay`)

| Rule | Checks |
|---|---|
| `relay/unused-fields` | Each selected field is used in the module that selects it. |
| `relay/must-colocate-fragment-spreads` | A module imports the module that defines each fragment it spreads. Depends on globally unique module names. |
| `relay/no-future-added-value` | Code does not handle the `%future added value` enum placeholder. |
| `relay/graphql-syntax` | Each `graphql` tag parses. |
| `relay/graphql-naming` | Fragment and operation names follow the Relay naming rules. |
| `relay/function-required-argument` | `readInlineData` gets an explicit argument. |
| `relay/hook-required-argument` | Relay hooks get an explicit argument. |

Config: `relay.configs['ts-recommended'].rules` in `eslint.config.js`. Suppress `unused-fields` and `must-colocate-fragment-spreads` with `# eslint-disable-next-line relay/<rule>` on the line before the field. `eslint-disable-line` does not work inside `graphql` tags.

### Babel plugin with `artifactDirectory`

When the compiler config sets `artifactDirectory`, the Babel plugin needs the same value:

```json
{
  "plugins": [["relay", { "artifactDirectory": "./src/__generated__" }]]
}
```

The `"relay"` plugin must run before other plugins or presets. The docs name framework plugins for Vite, Next.js and SWC.

---

## Diagnostic flowchart

| Symptom | First check | Fix |
|---|---|---|
| Console: inconsistent `__typename` | Do 2 types share a raw ID? | Prefix the ID of the less widely used type with a unique string and base64 encode it |
| `Expected a handler for deleteRecord` | Is a custom `handlerProvider` passed? | Return the `MutationHandlers.*` handlers |
| Field null in component | Response in the DevTools network panel | If null in the response, fix the server. Otherwise check for a graph relationship change or a client-side update |
| Console: two instances of the same id | Inspect the query response | Fix the field stability of the server |
| Works locally, fails in CI | Are generated artifacts committed and current? | Run `relay-compiler --validate` |
| Compiler: disallowed `id` type | Type of the `id` field in the schema | Type the field as `ID`, rename it, or list it in `nonNodeIdFields` |
