# Debugging Relay

Reference for diagnosing Relay issues: DevTools, store consistency, mutation directives, null fields, missing fields, compiler artifacts, and verbose environment logging. Hooks only.

## Relay DevTools

Browser extension for inspecting the Relay store, network traffic, and environment state at runtime.

### Installation

Install from the Chrome Web Store: "Relay Developer Tools" (id `ncedobpgnmkhcmnnkcimnobpfepidadl`). A `Relay` panel is added to Chrome DevTools. For Firefox, use the add-on of the same name.

Enable DevTools hook in your environment initialization — no special flag is needed; the extension detects any `RelayModernEnvironment` constructed on `window`. For SSR apps, DevTools only activate client-side after hydration.

### Environment selector

The top-left dropdown lists every active `Environment` instance. Multi-environment apps (e.g. logged-in vs anonymous) show each separately. Store and network panes are scoped to the selected environment — switching clears filters.

### Store inspector

Browse normalized records in the cache.

- Left column: scrollable list of record IDs (e.g. `User:42`, `client:root`, `client:root:viewer`).
- Right column: key/value view of the selected record — `__id`, `__typename`, scalar fields, and links (`__ref`, `__refs`).
- Click any `__ref` to jump to the referenced record.
- Search box filters by ID substring or `__typename`.
- "Copy as JSON" dumps the whole store to clipboard for offline diff.

Use it to confirm whether a field reached the store. If `User:42.name` is missing in the inspector, no component reading `user.name` will render it — the fetch or fragment spread is the problem, not React.

### Network inspector

Lists every `execute` call against the environment. Each row shows operation name, status, duration, variables, and the raw response. Click a row to expand:

- `Variables` — payload sent with the query.
- `Response` — exact GraphQL response, including `errors` array.
- `Metadata` — operation kind (`query` | `mutation` | `subscription`), cache config.

Mutations and subscriptions appear in the same list, tagged by kind. For subscriptions, each emitted payload is a new row under the subscription operation.

### Limitations

- No mutation optimistic-update diff view — use the store inspector before/after.
- No time-travel; refreshing the page clears history.
- Does not show garbage-collected records.

---

## Inconsistent Typename Error

### Symptom

Console error during normalization of a response:

```
RelayResponseNormalizer: Invalid record '543'. Expected __typename to be
consistent, but the record was assigned conflicting types User and
MessagingParticipant. The GraphQL server likely violated the globally unique
ID requirement by returning the same ID for different objects.
```

The store then contains a corrupted record. Subsequent fragment reads may return stale fields from the previous type.

### Root cause

Relay's store is normalized by record ID. When two responses return the same `id` for objects of different types, the second overwrites the first. The GraphQL spec (and Relay's Object Identification assumption) requires IDs to be globally unique across the entire schema, not just per-type.

Common triggers:

- Server returns raw database primary keys that collide across tables (`users.id=1` and `posts.id=1`).
- `id` is derived from an array index.
- Two types share a join table.

### Fixes

Prefer server-side fixes — client workarounds are fragile.

**Schema fix (preferred)**: encode type into the global ID. A common convention is `base64(Type:rawId)`, e.g. `VXNlcjox` for `User:1`. Keep resolvers symmetric with `node(id:)`.

**Client-side fix**: set a custom `getDataID` on the `Store` and on the `Environment` (see the placement note below):

```js
import { Environment, Network, RecordSource, Store } from 'relay-runtime';

const store = new Store(new RecordSource(), {
  getDataID: (fieldValue, typename) => `${typename}:${fieldValue.id}`,
});
```

This prefixes every record ID with its typename at normalization time, restoring uniqueness without server changes. Note: once set, you cannot later rely on raw `id` values as record IDs — `node(id:)` queries must use the same encoding.

**Verification**: after the fix, clear the store (`environment.getStore().publish(new RecordSource())`) or hard-reload; the error should not recur.

**`getDataID` placement**: `Environment` normalizes responses with its own `getDataID` option (`RelayModernEnvironment.js:141`, `:494`). An `Environment` built with an explicit `store` ignores a `getDataID` that only the `Store` receives. Pass `getDataID` in the `Environment` config as well:

```js
const getDataID = (fieldValue, typename) => `${typename}:${fieldValue.id}`;
const environment = new Environment({
  network,
  getDataID,
  store: new Store(new RecordSource(), { getDataID }),
});
```

The v21 docs recommend the server-side fix: prefix the id of the less widely used type with a unique string and base64-encode it, and make `node(id:)` resolve it.

---

## Debugging Declarative Mutation Directives

Directives `@appendEdge`, `@prependEdge`, `@appendNode`, `@prependNode`, `@deleteEdge`, `@deleteRecord` require runtime handlers.

### Error: handler not registered

```
RelayModernEnvironment: Expected a handler to be provided for handle `deleteRecord`.
```

or

```
RelayFBHandlerProvider: No handler defined for `deleteRecord`
```

**Cause**: a custom `handlerProvider` was passed to `Environment` without registering mutation handlers.

**Fix**: import `MutationHandlers` from `relay-runtime`. The documented handlers are `AppendEdgeHandler`, `PrependEdgeHandler`, and `DeleteRecordHandler`:

```js
import { Environment, MutationHandlers } from 'relay-runtime';

const handlerProvider = (handle) => {
  switch (handle) {
    case 'appendEdge': return MutationHandlers.AppendEdgeHandler;
    case 'prependEdge': return MutationHandlers.PrependEdgeHandler;
    case 'deleteRecord': return MutationHandlers.DeleteRecordHandler;
    default: return null;
  }
};

const environment = new Environment({ network, store, handlerProvider });
```

If you do not pass a `handlerProvider`, Relay uses the default which already includes all mutation handlers — the error only happens when you override it.

### Edge inserted but not visible

Symptoms: mutation succeeds, DevTools shows the new node in the store, but the list component does not re-render with it.

Checklist:

1. **Connection ID mismatch**. `@appendEdge(connections: $ids)` requires the exact connection ID. Get it via `ConnectionHandler.getConnectionID(parentId, 'FeedConnection', filters)`. Log the ID before calling the mutation and compare to the one visible in the store inspector (`client:User:42:__FeedConnection_connection(orderBy:"DATE")`).

2. **Missing `@connection` directive on the query**. Without `@connection(key: "FeedConnection")`, Relay does not track the list as a connection and has no stable ID to append to.

3. **Filter args not included in the key**. If the connection has non-paginating args (like `orderBy`), include them in `filters` on both the query and the edge directive — otherwise IDs differ.

4. **Edge shape mismatch**. Mutation response must return the edge in the exact shape of the connection's `edgeTypeName`, including `cursor` and `node { id }`. Missing `id` on the node means Relay cannot deduplicate.

5. **Wrong edge type name**. `@appendNode(edgeTypeName: "FeedEdge")` must match the schema's connection edge type.

### Edge deletion doesn't remove item

- `@deleteEdge(connections: $ids)` deletes by node ID. The mutation response must return the deleted node's `id` field.
- `@deleteRecord` deletes the record from the store. An edge that still points to the record reads `undefined`.

---

## Why is my field null?

Diagnostic flow when a component reads a field and gets `null` unexpectedly.

### 1. Check the server response

Open DevTools Network panel, find the operation, inspect `Response`. Is the field null in the raw payload?

- **Yes, null in response**: the resolver returned null or threw. GraphQL coerces resolver exceptions to null for nullable fields. Check server logs and the `errors` array in the response.
- **No, value present**: the value is in the response but null by the time the component reads it — continue below.

### 2. Check the fragment

```js
const data = useFragment(graphql`
  fragment UserCard_user on User {
    name
    # avatarUrl  <-- commented out = always null when read
  }
`, userRef);
```

If the field is not in the fragment, `data.avatarUrl` is `undefined` (TypeScript) or `null` — Relay only returns fields the fragment selects. Add the field and re-run the compiler.

### 3. Check for graph relationship changes

Relay's store is normalized. A component reads `viewer.bestFriend.name`. Later, another query/mutation updates `viewer.bestFriend` to point at a different `User` record whose `name` was never fetched. The component re-renders with `name: null`.

Relay prints no warning for this case. To confirm it, log the result at the final return statement of `readWithIdentifier` in `FragmentResource`, or inspect the record in the DevTools store panel.

Fix: ensure every query/mutation/subscription that can change the relationship selects all fields downstream components need. Use a shared fragment.

A different case has a console error: the server returns the same `id` 2 times in one response with different field values. Relay logs in development:

```
RelayResponseNormalizer: Invalid record. The record contains two instances of
the same id: 1 with conflicting field, name and its values: Alice and null.
```

Fix that on the server.

### 4. Check garbage collection

Records with no active subscribers are eligible for GC. A component that mounts, unmounts, then remounts may find its records evicted. Hooks-based Relay (`useLazyLoadQuery`, `useQueryLoader`) retains records only while the hook is mounted.

Symptoms: first render works, navigating away and back shows nulls. Fix by increasing GC retention or retaining the query:

```js
const [queryRef, loadQuery] = useQueryLoader(MyQuery);
// queryRef holds a retain ref; keeps records alive across unmounts of child.
```

Or configure the store: `new Store(source, { gcReleaseBufferSize: 10 })`.

### 5. Check `@required` behavior

```graphql
fragment User_profile on User {
  name @required(action: LOG)
  email @required(action: THROW)
}
```

- `action: NONE` — null is expected; parent becomes null, no log event.
- `action: LOG` — parent becomes null; `missing_required_field.log` event fires via the environment's field logger.
- `action: THROW` — throws during render; requires an error boundary.

`NONE` and `LOG` bubble null to the parent. If the parent is non-null in the schema, Relay makes the fragment root `null` — the whole component gets `data === null`. Remove `@required` to see raw nulls while debugging.

### 6. Check client-side updates

Optimistic updaters or imperative `commitLocalUpdate` can delete or partially populate records:

```js
environment.commitUpdate((store) => {
  const user = store.get('User:42');
  user.setValue(null, 'name'); // explicit null
});
```

The store inspector shows the current field values. If `name` is null there, a client updater wrote null.

---

## Why is my field not found?

Compile-time or runtime errors where a selected field appears missing.

### Compiler error: unknown field

```
Error: The type `User` has no field `avatarUrll`.
  ┌─ UserCard.tsx:4:5
  │
4 │     avatarUrll
  │     ^^^^^^^^^^ The type `User` has no field `avatarUrll`.
```

Typo or schema drift. The compiler suggests a replacement when one is close: ``The type `UserInfo` has no field `mail`. Did you mean `email`?`` Update the schema file the compiler points at (`relay.config.json` → `schema`).

### Compiler error: fragment not found

```
Error: Unknown fragment `UserCard_user`.
```

Causes:

1. The fragment file wasn't imported where it's spread. Relay compiler scans files matching `src` glob. If the fragment lives outside the scanned paths, it won't be found.
2. The fragment's file is ignored by `exclude` patterns.
3. File uses `.jsx` but `extensions` only lists `js`.

### Runtime: `data.fieldName` is `undefined`

- The fragment does not spread another fragment that selects the field.
- Generated artifacts are stale. Re-run the compiler:

```
yarn relay         # one-shot
yarn relay --watch # watch mode (needs watchman)
```

`__generated__/UserCard_user.graphql.ts` must contain the field in its selections. If not, the compiler didn't see your edit.

### Stale `__generated__` in CI

Symptoms: works locally, fails in CI with field-not-found. Cause: `__generated__` is gitignored but the CI compiler step is missing, so artifacts aren't rebuilt.

Fix: either check in `__generated__` or run `relay-compiler` in CI before the bundler. Add a check:

```
yarn relay --validate
```

`--validate` writes nothing and exits with a non-zero code when a committed artifact is out of date.

### Fragment spread missing

Parent query reads a field that belongs only to a child's fragment:

```graphql
query FeedQuery { viewer { ...UserCard_user } }
fragment UserCard_user on User { name }
```

Parent tries `data.viewer.email` — not selected anywhere. Add `email` to `UserCard_user` or to the query directly.

### `useFragment` returns unexpected shape

Always pass the fragment ref from the parent's `...Child_fragment` spread, not the full parent data:

```js
// wrong — passes the whole viewer object
useFragment(UserCard_user, data.viewer);

// correct — viewer is spread with ...UserCard_user in parent
useFragment(UserCard_user, data.viewer);
```

Types catch this when using the generated `FragmentType` imports.

---

## Verbose environment logging

Pass a `log` callback to `Environment` to receive every internal event.

```js
import { Environment, Network, RecordSource, Store } from 'relay-runtime';

const environment = new Environment({
  network: Network.create(fetchQuery),
  store: new Store(new RecordSource()),
  log: (event) => {
    console.log('[relay]', event.name, event);
  },
});
```

### Event names

- `execute.start` — operation starts; includes `variables`, `transactionID`.
- `execute.next.start` / `execute.next.end` — around each response payload.
- `execute.complete` — operation finished.
- `execute.error` — operation failed; includes `error`.
- `execute.unsubscribe` — subscription cancelled.
- `network.info` — network-layer info (e.g. cache hits).
- `network.start` / `network.next` / `network.complete` / `network.error`.
- `queryresource.fetch` — `useLazyLoadQuery` fetching.
- `queryresource.retain`.
- `store.publish` — records written to store; includes `source`.
- `store.gc.start` / `store.gc.interrupted` / `store.gc.end` — around garbage collection; `store.gc.end` includes `references` retained.
- `store.restore` — store restored from snapshot.
- `store.snapshot` — snapshot taken.
- `store.notify.start` / `store.notify.complete` — subscribers being notified.
- `entrypoint.root.consume` — entrypoint resource read.

The `LogEvent` type in `RelayStoreTypes.js` defines further events.

| Group | Events |
|---|---|
| Suspense | `suspense.fragment`, `suspense.query`, `suspense.resolver` (v21 only), `suspense.client_edge` (v21 only), `suspense.missing_data` (v21 only) |
| Reads | `fragmentresource.missing_data`, `pendingoperation.found`, `useFragment.subscription.missedUpdates`, `reader.fragmentSpread` (v21 only), `reader.read` (v21 only), `fetchquery.fetch` (v21 only) |
| Network and execute | `network.unsubscribe`, `execute.async.module`, `execute.normalize.start`, `execute.normalize.end` |
| Store | `store.datachecker.start`, `store.datachecker.end`, `store.datachecker.missing` (v21 only), `store.lookup.start`, `store.lookup.end`, `store.batch.start` (v21 only), `store.batch.complete` (v21 only), `store.notify.subscription` |
| Resolvers | `liveresolver.batch.start`, `liveresolver.batch.end` |
| Identity | `idCollision.typename` (fields `previous_typename`, `new_typename`) |

`idCollision.typename` fires when 2 objects share an id and have different types. It needs `RelayFeatureFlags.ENABLE_STORE_ID_COLLISION_LOGGING` set to `true`.

Filter noise in dev:

```js
log: (event) => {
  if (event.name.startsWith('store.gc')) return;
  console.log(event.name, event);
}
```

### Field-missing logger

Separate from `log`: `relayFieldLogger` receives `missing_required_field.log` and `missing_expected_data.log` events. Useful for wiring `@required(action: LOG)` into Sentry:

```js
new Environment({
  network, store,
  relayFieldLogger: (event) => {
    if (event.kind === 'missing_required_field.log') {
      Sentry.captureMessage(`@required null: ${event.owner}.${event.fieldPath}`);
    }
  },
});
```

The logger receives 6 event kinds. `owner` is the name of the operation or fragment. `fieldPath` is the dot-separated path from its root to the field.

| `event.kind` | When it fires |
|---|---|
| `missing_expected_data.log` | The store lacks data that the parent query selected. Relay renders the field as `undefined`. |
| `missing_expected_data.throw` | The same, inside an operation or fragment with `@throwOnFieldError`. Relay throws after the logger returns. |
| `missing_required_field.log` | A `@required(action: LOG)` field is null or missing. |
| `missing_required_field.throw` | A `@required(action: THROW)` field is null or missing. |
| `relay_resolver.error` | A Relay Resolver threw. Relay coerces the error to null. |
| `relay_field_payload.error` | The server response has a field-level error. |

The `.throw`, `relay_resolver.error` and `relay_field_payload.error` events carry `handled`. Throw a custom error from the logger only when `handled` is `false`. A `@catch` directive or a null resolver result sets `handled` to `true`.

---

## Reading generated artifacts

Every `graphql` tagged template compiles to a file in `__generated__/`. Reading it answers "what does Relay think my query looks like?"

### File layout

```
src/components/UserCard.tsx
src/components/__generated__/UserCard_user.graphql.ts
```

The artifact exports:

- `node` — the `ReaderFragment` or `ConcreteRequest` Relay executes.
- Type exports — `UserCard_user$data`, `UserCard_user$key`.

### What to check

- `node.selections` — the exact field list. If a field you wrote isn't here, your edit didn't reach the compiler (cache issue: delete `__generated__` and rerun).
- `node.argumentDefinitions` — variables the fragment accepts.
- For queries, `params.text` is the serialized query string sent to the server. Paste it into GraphiQL to test the server independently.
- `node.metadata.connection` — connection config for `@connection` fragments.

### Stale artifact symptoms

- Added `@required` but no `required` field in `node.selections`.
- Renamed a fragment but the old artifact still exists.
- Imports resolve but types don't match runtime data.

Fix: `rm -rf src/**/__generated__` then `yarn relay`.

---

## Common compiler errors

### Duplicate fragment name

```
Error: Duplicate definition for fragment `UserCard_user`.
```

Two files define the same fragment. Fragment names must be globally unique across the project. Convention: `ComponentName_propName`.

### Invalid `@connection`

```
Error: Expected the `key` argument to `@connection` to be a string literal.
```

`@connection(key: $keyVar)` not allowed — must be a string literal. Also: key must match pattern `<FragmentName>_<fieldName>`.

### `@refetchable` without `Node`

```
Error: @refetchable fragments must be on a type that implements Node or Viewer.
```

Add `Node` interface implementation to the type in your schema, or use `@refetchable(queryName: "…")` on a fragment whose type has a unique identifier.

### Circular fragment spread

```
Error: Fragment `A` spreads fragment `B` which spreads fragment `A`.
```

Break the cycle — one fragment should not transitively include itself.

---

### Disallowed `id` type

```
Disallowed type `String` of field `id` on parent type `Foo` cannot be used by Relay to identify entities
```

The compiler accepts only `ID` or `ID!` for an `id` field outside the `Node` interface. Rename the field, or type it as `ID`. To keep the field, list the type and its `id` type in `nonNodeIdFields` (v21 docs; schema on the main branch):

```json
{
  "relay": {
    "schemaConfig": {
      "nonNodeIdFields": { "allowedIdTypes": { "Foo": "String" } }
    }
  }
}
```

The allowlist skips the check for that pair only. Components that select that `id` can stop re-rendering after a refetch.

---

## Compiler Tooling Reference

### Config file locations

The compiler searches these locations, in the order the v20.1 and v21.0.1 docs list them:

1. `relay.config.json` in the project root
2. `relay.config.(js|mjs|ts)` in the project root
3. A `"relay"` key in `package.json`

Pass a path as the positional `[CONFIG]` argument to override the search.

### Multi-project config

The compiler config schema on the main branch has 2 shapes. A single project uses top-level keys such as `src`, `schema` and `language`. Several projects use `sources`, `projects` and `generatedSources`. Each entry in `projects` takes `schema`, `schemaDir`, `output`, `base` and `persist`. The v21 docs do not describe this shape. Confirm the key names against your installed version with `relay-compiler config-json-schema`.

### Compiler CLI flags

| Flag | v20.1.1 | v21.0.1 | Effect |
|---|---|---|---|
| `--watch`, `-w` | yes | yes | Recompile on change. Needs watchman. |
| `--project`, `-p` | yes | yes | Compile one project. Repeat for several. |
| `--src`, `--schema`, `--artifactDirectory` | yes | yes | Rejected. The compiler does not accept a config on the command line; use a config file. |
| `--repersist` | yes | yes | Run the persister even when a query did not change. |
| `--validate` | yes | yes | Exit non-zero when artifacts are out of date. Write nothing. |
| `--output` | yes | yes | Set the log level: `debug`, `quiet`, `quiet-with-errors`, `verbose`. |
| `--noWatchman` | absent | yes | Use directory traversal. Conflicts with `--watch`. The v21 docs write `--no-watchman`; the clap definition uses camel case, so the source name is `--noWatchman`. The env variable `FORCE_NO_WATCHMAN` has the same effect on both versions. |
| `config-json-schema` | yes | yes | Print the config JSON schema. |
| `codemod <cmd>` | yes (2 commands) | yes (3 commands) | `fix-all` is absent on v20.1.1. The source of `fix-all` sits in `relay-codemod/src/codemod.rs`. |
| `lsp` | yes | yes | Run the language server. `--locateCommand <script>` finds the definition for implementation-first schemas. |
| `experimental-compare-document-ir` | absent | yes | Compare the IR of two documents. Experimental. |
| `experimental-regenerate-sub-schema` | absent | yes | Replace the schema with the part the project uses. Experimental. |

`relay-compiler --help` prints the full list for your installed version.

### Document comparison (v21 only, experimental)

`relay-compiler experimental-compare-document-ir --left <doc> --right <doc> --schemaPaths <schema>...` checks that every selection of `--left` exists in `--right`. Each document holds exactly 1 operation. The compiler inlines fragments, removes aliases and duplicate fields, and treats `user(id: $id)` as a superset of `user(id: 100)`. The output lists the missing selections with line numbers and paths, for example `* query -> viewer -> timezone_estimate -> gmt_offset`. Swap the arguments to find extra selections (over-fetching).

### Codemods

`relay-compiler codemod <name> [CONFIG] [-p <project>]` runs one of: `mark-dangerous-conditional-fragment-spreads` (option `-r`/`--rollout-percentage`), `remove-unnecessary-required-directives` and `fix-all` (v21 only). `fix-all` applies the fix of every fixable diagnostic. Run it after a Relay upgrade.

### VS Code extension and LSP

The Relay VS Code extension (marketplace id `meta.relay`) runs the compiler's LSP server. It gives compiler errors as editor problems, autocomplete and hover inside `graphql` tags, click-to-definition and quick fixes. The extension reads the same config file as the CLI. The v21 docs and the v20.1 docs name the same extension.

### ESLint plugin (`eslint-plugin-relay`)

Source: the v21 docs. The plugin package sits outside the Relay repository, so the rule behavior is not checked against source here.

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

The Babel plugin must run before other plugins. The v21 docs name framework plugins for Vite, Next.js and SWC.

---

## Diagnostic flowchart

| Symptom | First check | Second check | Fix |
|---|---|---|---|
| Console: inconsistent `__typename` | DevTools store inspector for the ID | Are two types sharing raw IDs? | Encode typename into ID on server, or set `getDataID` on Environment and Store |
| `Expected a handler for deleteRecord` | Custom `handlerProvider` passed? | Does it cover all mutation handles? | Register `MutationHandlers.*` handlers |
| `@appendEdge` inserts but list doesn't update | Connection ID in store | Does mutation's `connections` array match exactly? | Use `ConnectionHandler.getConnectionID` with same filters |
| Field null in component | DevTools Network response | Is value null in raw payload? | Fix server resolver or add field to fragment |
| Field null after navigation | DevTools store inspector | Record evicted by GC? | Increase `gcReleaseBufferSize` or retain with `useQueryLoader` |
| Non-null schema field is null | Is `@required` on a child? | `action: LOG` or `THROW`? | Remove `@required` to see the raw null, or add error boundary |
| `data.field` is undefined | Fragment selections in `__generated__` artifact | Is the field present? | Re-run `relay-compiler` |
| Compiler: Unknown fragment | Is file under `src` glob? | Is it in `exclude`? | Update `relay.config.json` |
| Compiler: type has no field X | Schema file fresh? | Pointed at right `.graphql`? | Update schema, rerun compiler |
| Works locally, fails in CI | `__generated__` in git? | Is `relay-compiler` in CI? | Add `yarn relay` before build |
| Fragment read returns wrong shape | Which ref passed to `useFragment`? | Is it from a `...Fragment_x` spread? | Pass spread ref, not raw data |
| Mutation works, store not updated | Is response shape matching fragment? | Are IDs globally unique? | Ensure response selects `id` and all fragment fields |
| Subscription fires but no rerender | Network panel shows payload? | Store inspector shows updated record? | Check subscription selects full fragment |
| Duplicate fragment error | Two files with same fragment name | Rename one | Use `Component_propName` convention |
| @refetchable error | Type implements `Node`? | Has `id: ID!`? | Implement `Node` in schema |
| Console warning: missing expected data | Which fragment owner? | Recent mutation touched record? | Select all required fields in mutation response |
