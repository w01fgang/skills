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
RelayResponseNormalizer: Invalid record. Expected __typename to be consistent,
but the record was assigned conflicting types User and MessagingParticipant.
The GraphQL server likely violated the globally unique id requirement by
returning the same id for different objects.
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

**Client-side fix**: set a custom `getDataID` on the `Store`:

```js
import { Environment, Network, RecordSource, Store } from 'relay-runtime';

const store = new Store(new RecordSource(), {
  getDataID: (fieldValue, typename) => `${typename}:${fieldValue.id}`,
});
```

This prefixes every record ID with its typename at normalization time, restoring uniqueness without server changes. Note: once set, you cannot later rely on raw `id` values as record IDs — `node(id:)` queries must use the same encoding.

**Verification**: after the fix, clear the store (`environment.getStore().publish(new RecordSource())`) or hard-reload; the error should not recur.

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
- `@deleteRecord` removes the record from the store entirely. Any component still referencing it will see fields as null.

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

Console warning in development:

```
RelayResponseNormalizer: Invalid record `User:17`. Expected field `name`
to be present but it was not found.
```

Fix: ensure every query/mutation/subscription that can change the relationship selects all fields downstream components need. Use a shared fragment.

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

- `action: NONE` — null allowed, no action.
- `action: LOG` — parent becomes null; `missing_required_field.log` event fires via the environment's field logger.
- `action: THROW` — throws during render; requires an error boundary.

A `@required(action: LOG)` field bubbles null to the parent. If the parent is non-null in the schema, Relay makes the fragment root `null` — the whole component gets `data === null`. Remove `@required` or downgrade to `NONE` to see raw nulls while debugging.

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

Typo or schema drift. Update the schema file the compiler points at (`relay.config.json` → `schema`).

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
yarn relay --watch # watch mode
```

`__generated__/UserCard_user.graphql.ts` must contain the field in its selections. If not, the compiler didn't see your edit.

### Stale `__generated__` in CI

Symptoms: works locally, fails in CI with field-not-found. Cause: `__generated__` is gitignored but the CI compiler step is missing, so artifacts aren't rebuilt.

Fix: either check in `__generated__` or run `relay-compiler` in CI before the bundler. Add a check:

```
yarn relay && git diff --exit-code
```

This fails CI if committed artifacts are out of sync.

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
- `execute.next` — response payload received.
- `execute.complete` — operation finished.
- `execute.error` — operation failed; includes `error`.
- `execute.unsubscribe` — subscription cancelled.
- `network.info` — network-layer info (e.g. cache hits).
- `network.start` / `network.next` / `network.complete` / `network.error`.
- `queryresource.fetch` — `useLazyLoadQuery` fetching.
- `queryresource.retain` / `queryresource.release`.
- `store.publish` — records written to store; includes `source`.
- `store.gc` — garbage collection ran; includes `references` retained.
- `store.restore` — store restored from snapshot.
- `store.snapshot` — snapshot taken.
- `store.notify.start` / `store.notify.complete` — subscribers being notified.
- `entrypoint.root.consume` — entrypoint resource read.

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

### Missing `id` on connection node

```
Error: Expected connection edge node to have an `id` selection.
```

Add `node { id }` to the connection's edge selection. Relay needs `id` to deduplicate edges.

### Circular fragment spread

```
Error: Fragment `A` spreads fragment `B` which spreads fragment `A`.
```

Break the cycle — one fragment should not transitively include itself.

---

## Diagnostic flowchart

| Symptom | First check | Second check | Fix |
|---|---|---|---|
| Console: inconsistent `__typename` | DevTools store inspector for the ID | Are two types sharing raw IDs? | Encode typename into ID on server, or set `getDataID` on Store |
| `Expected a handler for deleteRecord` | Custom `handlerProvider` passed? | Does it cover all mutation handles? | Register `MutationHandlers.*` handlers |
| `@appendEdge` inserts but list doesn't update | Connection ID in store | Does mutation's `connections` array match exactly? | Use `ConnectionHandler.getConnectionID` with same filters |
| Field null in component | DevTools Network response | Is value null in raw payload? | Fix server resolver or add field to fragment |
| Field null after navigation | DevTools store inspector | Record evicted by GC? | Increase `gcReleaseBufferSize` or retain with `useQueryLoader` |
| Non-null schema field is null | Is `@required` on a child? | `action: LOG` or `THROW`? | Downgrade to `NONE` or add error boundary |
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
