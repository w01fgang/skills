# Network Layer & Server Integration

Relay is transport-agnostic. You provide a `Network` that knows how to turn GraphQL operations into responses — HTTP, WebSocket, HTTP/2 multipart, whatever. This reference covers how to build that layer for a hooks-based Relay app and the schema contract your server must honor.

---

## 1. `Network.create` — the entry point

```js
import { Network } from 'relay-runtime';

const network = Network.create(fetchFn, subscribeFn);
```

Signature:

```ts
Network.create(
  fetchFn: (
    request: RequestParameters,
    variables: Variables,
    cacheConfig: CacheConfig,
    uploadables?: UploadableMap,
  ) => ObservableFromValue<GraphQLResponse>,
  subscribeFn?: (
    request: RequestParameters,
    variables: Variables,
    cacheConfig: CacheConfig,
  ) => RelayObservable<GraphQLResponse>,
): INetwork
```

- `fetchFn` handles queries and mutations.
- `subscribeFn` is optional. Omit it and subscriptions throw. Provide it to wire WebSockets / SSE.
- Both functions may return a `Promise`, a plain value, or a `RelayObservable`. Returning an Observable is required for `@defer`, `@stream`, and subscriptions (multiple payloads).

`Network.create` is then handed to the `Environment`:

```js
import { Environment, RecordSource, Store } from 'relay-runtime';

const environment = new Environment({
  network,
  store: new Store(new RecordSource()),
});
```

---

## 2. The `fetchFn` arguments

```js
function fetchFn(request, variables, cacheConfig, uploadables) { ... }
```

| Arg | Type | What it is |
|-----|------|-----------|
| `request` | `RequestParameters` | Operation metadata. Use `request.text` (query string) or `request.id` (persisted id). Also has `request.name` and `request.operationKind` (`'query' \| 'mutation' \| 'subscription'`). |
| `variables` | `Variables` | Plain object of variables for this operation. |
| `cacheConfig` | `CacheConfig` | `{ force?: boolean, poll?: number, liveConfigId?: string, metadata?: object, transactionId?: string }`. `force: true` means: issue the request regardless of the state of a configured response cache. `useLazyLoadQuery`, `loadQuery` and `fetchQuery` default `networkCacheConfig` to `{ force: true }`. |
| `uploadables` | `UploadableMap \| null` | `{ [key: string]: File \| Blob }` when a mutation was issued with uploadables. Null otherwise. |

### Minimal fetchFn

```js
async function fetchFn(request, variables) {
  const response = await fetch('/graphql', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ query: request.text, variables }),
  });
  return response.json();
}
```

This is enough for plain queries/mutations without uploads, `@defer`, `@stream`, or persisted queries.

---

## 3. Relay's `Observable`

Relay ships its own push-based `Observable` (not RxJS, not the TC39 proposal — compatible in spirit). It is the correct return type for any operation that yields more than one payload.

```js
import { Observable } from 'relay-runtime';
```

### Create one

```js
const stream = Observable.create((sink) => {
  sink.next(payload1);
  sink.next(payload2);
  sink.complete();
  return () => {
    // cleanup on unsubscribe
  };
});
```

`sink` has `next(value)`, `error(err)`, `complete()`, and `closed`.

### Adapt a Promise

```js
Observable.from(fetch('/graphql', ...).then(r => r.json()));
```

### Adapt a foreign Observable

```js
Observable.from({
  subscribe(observer) {
    const sub = otherObservable.subscribe({
      next: v => observer.next(v),
      error: e => observer.error(e),
      complete: () => observer.complete(),
    });
    return { unsubscribe: () => sub.unsubscribe() };
  },
});
```

---

## 4. Authentication headers

Headers belong inside `fetchFn`. Read tokens at request time so they stay fresh.

```js
function getAuthToken() {
  return window.localStorage.getItem('access_token');
}

async function fetchFn(request, variables) {
  const token = getAuthToken();
  const res = await fetch('/graphql', {
    method: 'POST',
    credentials: 'include', // send cookies (CSRF / session)
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      'X-Client-Version': BUILD_VERSION,
    },
    body: JSON.stringify({ query: request.text, variables }),
  });

  if (res.status === 401) {
    await refreshToken();
    throw new Error('Unauthorized — retry with new token');
  }

  return res.json();
}
```

For token refresh mid-flight, wrap the above in a retry helper or return an `Observable` that retries once on 401.

---

## 5. Persisted queries

Persisted queries replace the operation text sent over the wire with a hash id. Two benefits: smaller requests, and an allowlist the server can enforce.

### Client compiler config (`package.json`)

```json
{
  "relay": {
    "src": "./src",
    "schema": "./schema.graphql",
    "language": "typescript",
    "persistConfig": {
      "url": "http://localhost:2999/persist",
      "params": {}
    }
  }
}
```

Without `persistConfig`, generated artifacts contain `text: "query ..."` and `id: null`. With it, `text: null` and `id: "<md5 hash>"`. The compiler POSTs each operation to `url` during build and stores the returned id.

Local file alternative (no persistence server):

```json
"persistConfig": {
  "file": "./persisted_queries.json",
  "algorithm": "MD5"
}
```

Ship `persisted_queries.json` to the server at deploy time. The browser bundle needs the file only with the Automatic Persisted Queries handshake.

### `persistConfig` options

`persistConfig` converts the text of every query and mutation into an id. The same options exist on v20.1 and v21.

| Key | Meaning |
|---|---|
| `url` | The compiler sends one POST request for each operation. The body is form-encoded (`application/x-www-form-urlencoded`) with the parameter `text`. The endpoint answers with JSON `{ "id": "<id>" }`. |
| `params` | Extra form parameters that the compiler adds to the POST body. |
| `file` | Path of a local JSON file. The compiler writes the map `id → operation text` to it. Use `file` or `url`. |
| `algorithm` | Hash for the local file: `MD5`, `SHA256` or `SHA1`. The default is `MD5`. |

The compiler config schema on the `main` branch lists more keys. They are not confirmed for v21.0.1. Print the schema of your installed version with `relay-compiler config-json-schema` before you use them.

- Remote: `headers`, `concurrency`, `includeQueryText`.
- Local: `include_query_text` (snake case).
- A multi-project config names the option `persist`.

The flag `relay-compiler --repersist` runs the persister even when a query did not change.

### Persist endpoint contract

```js
// Minimal persist endpoint: POST text=<operation> -> { id }
const params = new URLSearchParams(body);
const text = params.get('text');
if (text == null) return res.writeHead(400).end('Expected `text` parameter');
const id = md5(text); // the same algorithm as the client expects
queryMap.set(id, text);
res.end(JSON.stringify({ id }));
```

### Get the query map to the server

| Setup | Approach |
|---|---|
| Client and server share one project | Both read the map file from a common location. |
| Separate projects | Push the map at compile time: `"relay": "relay-compiler && npm run push-queries"`. The script can `git push` to the server repository or save the map to a database. |
| Server has no map | Implement the Automatic Persisted Queries handshake. A cache miss costs 1 extra round trip, and the map file ships to the browser, which increases the bundle size. The server recovers by itself when its store is wiped. |

With Express, the `persistedQueries` middleware from `express-graphql-persisted-queries` resolves the id:

```js
app.use(
  '/graphql',
  persistedQueries({ queryMap, queryIdKey: 'doc_id' }),
  graphqlHTTP({ schema })
);
```

`relay-compiler --watch` together with `persistConfig` regenerates the query map on every change. This fits only an app where client and server run together on localhost and the server hot-reloads the map file.

### fetchFn for persisted queries

```js
async function fetchFn(request, variables) {
  const body = request.id
    ? { doc_id: request.id, variables }
    : { query: request.text, variables }; // dev fallback

  const res = await fetch('/graphql', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json();
}
```

### Server

The server receives `doc_id`, looks up the query text in its map, and executes as normal. Reject requests whose `doc_id` is not in the map to close the allowlist.

```js
// Express example
app.post('/graphql', async (req, res) => {
  const { doc_id, query, variables } = req.body;
  const text = doc_id ? queryMap[doc_id] : query;
  if (!text) return res.status(400).json({ errors: [{ message: 'Unknown doc_id' }] });
  const result = await graphql({ schema, source: text, variableValues: variables });
  res.json(result);
});
```

---

## 6. File uploads via `uploadables`

Trigger by passing an `uploadables` map to `commitMutation`:

```js
commitMutation(environment, {
  mutation: UploadAvatarMutation,
  variables: { input: { file: null } },
  uploadables: { 'variables.input.file': fileFromInput },
});
```

Then in `fetchFn`, detect `uploadables` and build a `multipart/form-data` body instead of JSON:

```js
async function fetchFn(request, variables, cacheConfig, uploadables) {
  const body = buildBody(request, variables, uploadables);
  const headers = uploadables
    ? {}                                  // let the browser set boundary
    : { 'Content-Type': 'application/json' };

  const res = await fetch('/graphql', { method: 'POST', headers, body });
  return res.json();
}

function buildBody(request, variables, uploadables) {
  if (!uploadables) {
    return JSON.stringify({ query: request.text, id: request.id, variables });
  }
  const form = new FormData();
  form.append('query', request.text ?? '');
  if (request.id) form.append('doc_id', request.id);
  form.append('variables', JSON.stringify(variables));
  for (const key of Object.keys(uploadables)) {
    if (Object.prototype.hasOwnProperty.call(uploadables, key)) {
      form.append(key, uploadables[key]);
    }
  }
  return form;
}
```

Critical: do not set `Content-Type` manually for multipart. The browser must add the boundary parameter itself.

The server side varies by stack (graphql-upload, apollo-upload-server, a plain multipart parser). It must resolve the form fields back into the `variables` tree using the field keys Relay sent.

---

## 7. Subscriptions — `subscribeFn` over `graphql-ws`

`graphql-ws` is the current recommendation (`subscriptions-transport-ws` is deprecated).

```bash
npm install graphql-ws
```

```js
import { Network, Observable } from 'relay-runtime';
import { createClient } from 'graphql-ws';

const wsClient = createClient({
  url: 'wss://api.example.com/graphql',
  connectionParams: () => ({
    authToken: getAuthToken(),
  }),
  retryAttempts: 5,
  shouldRetry: () => true,
});

function subscribeFn(request, variables) {
  return Observable.create((sink) => {
    if (!request.text) {
      sink.error(new Error('Subscription missing query text'));
      return;
    }
    return wsClient.subscribe(
      {
        operationName: request.name,
        query: request.text,
        variables,
      },
      {
        next: (payload) => sink.next(payload),
        error: (err) => sink.error(err),
        complete: () => sink.complete(),
      },
    );
  });
}

const network = Network.create(fetchFn, subscribeFn);
```

`wsClient.subscribe` returns an unsubscribe function — returning it from `Observable.create`'s callback lets Relay tear down the WS subscription when the consumer disposes.

Use the hook `useSubscription` to consume:

```js
import { useSubscription } from 'react-relay';
import { graphql } from 'relay-runtime';

const config = useMemo(() => ({
  subscription: graphql`subscription CommentAddedSubscription($postId: ID!) {
    commentAdded(postId: $postId) { id body }
  }`,
  variables: { postId },
}), [postId]);

useSubscription(config);
```

`useSubscription` and `requestSubscription` accept these config fields:

| Field | Purpose |
|---|---|
| `subscription` | The `graphql` literal. |
| `variables` | Variables for the subscription. |
| `onNext` | Runs for each payload. It receives the response up to the fragment spread boundaries. |
| `onError` | Runs when the subscription fails. |
| `onCompleted` | Runs when the server ends the subscription. |
| `updater` | Imperative store update for each payload. |

- Memoize the config object. `useSubscription` disposes and re-creates the subscription when the config identity changes.
- Relay establishes the subscription when the hook commits. It does not subscribe during render.
- Spread the fragments of the components that show the data in the subscription selection. Those components then update from the payload.
- `@deleteRecord`, `@appendEdge` and `@prependEdge` work in subscriptions.
- The legacy `subscriptions-transport-ws` client needs `Observable.from(client.request({ query: request.text, operationName: request.name, variables }))` to convert its observable to the Relay type.

---

## 8. Multipart responses for `@defer` / `@stream`

When a query uses `@defer` or `@stream`, the server responds with `multipart/mixed` and streams patches. Relay expects multiple `sink.next(...)` calls, one per part.

Use [`meros`](https://github.com/maraisr/meros) for browser/Node parsing:

```bash
npm install meros
```

```js
import { Observable } from 'relay-runtime';
import { meros } from 'meros';

function fetchFn(request, variables) {
  return Observable.create((sink) => {
    const controller = new AbortController();

    (async () => {
      try {
        const response = await fetch('/graphql', {
          method: 'POST',
          signal: controller.signal,
          headers: {
            'Content-Type': 'application/json',
            Accept: 'multipart/mixed; deferSpec=20220824, application/json',
          },
          body: JSON.stringify({ query: request.text, variables }),
        });

        const parts = await meros(response);

        if (!isAsyncIterable(parts)) {
          sink.next(await parts.json());
          sink.complete();
          return;
        }

        for await (const part of parts) {
          if (!part.json) {
            sink.error(new Error('Expected JSON part'));
            return;
          }
          sink.next(part.body);
        }
        sink.complete();
      } catch (err) {
        if (!controller.signal.aborted) sink.error(err);
      }
    })();

    return () => controller.abort();
  });
}

function isAsyncIterable(input) {
  return input != null && typeof input[Symbol.asyncIterator] === 'function';
}
```

The `Accept` header signals the server to stream. Without an iterable body Relay gets a single payload as before.

### Payload shape that Relay reads

`OperationExecutor` splits the parts that `sink.next` receives into initial and incremental payloads.

| Part | Required fields |
|---|---|
| Initial | `data` (and `errors` when present) |
| `@defer` | `data` for the deferred selection, `path` (array of keys), `label` (string) |
| `@stream` | `data` holds 1 list item, `path` ends with the field name and the item index, `label` |

- `path` and `label` are both present or both absent. Otherwise Relay throws `invalid incremental payload`.
- `sink.next` also accepts an array of payloads.
- Relay reads `data`, `path` and `label` at the top level of a part. The Relay runtime has no handling for an `incremental` array. If the server groups parts in `incremental`, split them in `fetchFn` before `sink.next`.
- A payload with `extensions: { is_final: true }` marks the last payload. If the first payload is final and the operation contains `@defer` or `@stream`, Relay logs a warning that the server ran in non-streaming mode.
- `deferDeduplicatedFields: true` in the `Environment` config stops Relay from throwing on fields that a deferred response omits (v21 only; absent in the v20.1.1 source). Use it when the server follows a spec proposal that does not repeat fields in deferred responses.

---

## 9. Request batching

Batching combines multiple concurrent operations into one HTTP request. Relay does not ship batching in core — implement it in `fetchFn` with a queue flushed on `Promise.resolve()` (microtask boundary).

```js
let queue = [];
let flushScheduled = false;

function enqueue(op) {
  return new Promise((resolve, reject) => {
    queue.push({ op, resolve, reject });
    if (!flushScheduled) {
      flushScheduled = true;
      queueMicrotask(flush);
    }
  });
}

async function flush() {
  const batch = queue;
  queue = [];
  flushScheduled = false;

  try {
    const res = await fetch('/graphql/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(batch.map(b => b.op)),
    });
    const results = await res.json(); // array, index-aligned
    batch.forEach((b, i) => b.resolve(results[i]));
  } catch (err) {
    batch.forEach(b => b.reject(err));
  }
}

function fetchFn(request, variables, cacheConfig, uploadables) {
  // Never batch uploads
  if (uploadables) {
    return fetchSingle(request, variables, uploadables);
  }
  return enqueue({ query: request.text, id: request.id, variables });
}
```

Server must accept an array of operations and return an index-aligned array of results. Keep a max batch size and a timeout backstop.

---

## 10. Error handling

GraphQL has two error channels and Relay surfaces both differently.

| Layer | How to signal | How Relay reacts |
|-------|---------------|------------------|
| Network/transport (non-2xx, aborted, parse fail) | Throw / `sink.error(err)` | `useLazyLoadQuery` throws, error boundary catches. `commitMutation.onError` fires. |
| GraphQL `errors` array | Return `{ data, errors }` | Relay raises iff `data` is nullish and field was non-nullable. `onCompleted(data, errors)` receives both. |

Rules of thumb:

- Treat 5xx and network failures as transport errors — throw or `sink.error`.
- Treat 200 with `{ errors: [...] }` as the GraphQL path. Let Relay decide based on nullability.
- Never swallow `errors` — always forward them.

```js
async function fetchFn(request, variables) {
  let res;
  try {
    res = await fetch('/graphql', { /* ... */ });
  } catch (err) {
    throw new NetworkError('Fetch failed', { cause: err });
  }
  if (!res.ok) {
    throw new NetworkError(`HTTP ${res.status}`, { status: res.status });
  }
  const json = await res.json();
  return json; // { data, errors? } — hand off verbatim
}

class NetworkError extends Error {
  constructor(msg, meta) { super(msg); Object.assign(this, meta); }
}
```

For subscriptions, `sink.error` kills the subscription. If the socket drops, `graphql-ws` with `retryAttempts` reconnects transparently; the subscription resumes from the server's perspective.

---

## 11. GraphQL server requirements for Relay

Relay assumes a specific shape on the server. Three contracts matter.

### 11.1 Node interface (Global Object Identification)

Every refetchable type implements:

```graphql
interface Node {
  id: ID!
}
```

And the root `Query` exposes:

```graphql
type Query {
  node(id: ID!): Node
}
```

`id` must be globally unique across all types. A common encoding is base64 of `"TypeName:localId"`. Relay uses `node(id:)` to refetch individual records for cache consistency and `refetch` hooks.

### 11.2 Connection specification (pagination)

List fields that support pagination conform to:

```graphql
type UserConnection {
  edges: [UserEdge]
  pageInfo: PageInfo!
}

type UserEdge {
  cursor: String!
  node: User
}

type PageInfo {
  hasNextPage: Boolean!
  hasPreviousPage: Boolean!
  startCursor: String
  endCursor: String
}
```

Connection fields take `first/after` (forward) or `last/before` (backward). Cursors are opaque strings. This is the contract `usePaginationFragment` relies on; without it, pagination cannot be generated.

Relay makes two core assumptions about the server: a mechanism to refetch an object (11.1) and a description of how to page through connections (11.2). The base64 form of ids and cursors is a convention that marks them as opaque. Pass to `node(id:)` only an unaltered `id` that the server returned.

If the server uses other names for the connection fields, set the names in both places. The values must match.

```json
{
  "relay": {
    "schemaConfig": {
      "connectionInterface": { "endCursor": "end_cursor", "hasNextPage": "has_next_page" }
    }
  }
}
```

```ts
import { ConnectionInterface } from 'relay-runtime';

ConnectionInterface.inject({
  END_CURSOR: 'end_cursor',
  HAS_NEXT_PAGE: 'has_next_page',
  HAS_PREV_PAGE: 'has_previous_page',
  START_CURSOR: 'start_cursor',
  PAGE_INFO: 'page_info',
  NODE: 'node',
  CURSOR: 'cursor',
  EDGES: 'edges',
  PAGE_INFO_TYPE: 'PageInfo',
});
```

### 11.3 Mutations

Relay recommends single-argument, named input mutations:

```graphql
type Mutation {
  createPost(input: CreatePostInput!): CreatePostPayload
}

input CreatePostInput {
  title: String!
  clientMutationId: String
}

type CreatePostPayload {
  post: Post
  clientMutationId: String
}
```

`clientMutationId` is optional in modern Relay but harmless to include.

### 11.4 Other server contracts

- Return `__typename` on all polymorphic positions (abstract types). Relay normalizes using it.
- `null` vs missing: a field explicitly returning `null` clears a cached value; an omitted field is ignored by the store.
- Keep IDs stable for a given logical entity. If the server returns a new `id` for the same object, Relay treats them as distinct records.

---

## 12. Client schema extensions (local-only state)

Sometimes you want client-only fields alongside server data. Add a `.graphql` file listed in `schemaExtensions`:

```graphql
# src/clientSchema.graphql
extend type User {
  isFavorited: Boolean
}

type DraftNote {
  id: ID!
  body: String
}

extend type Query {
  drafts: [DraftNote!]!
}
```

```json
{
  "relay": {
    "schemaExtensions": ["./src/clientSchema.graphql"]
  }
}
```

Query client fields alongside server fields:

```js
const data = useLazyLoadQuery(graphql`
  query UserQuery($id: ID!) {
    user: node(id: $id) {
      ... on User { id name isFavorited }
    }
  }
`, { id });
```

Write to local fields with `commitLocalUpdate` — the network layer never sees these fields.

---

## 13. Type emission (so `fetchFn` consumers stay typed)

Set a single artifact directory to get cross-file fragment reference types:

```json
{
  "relay": {
    "language": "typescript",
    "artifactDirectory": "./src/__generated__"
  }
}
```

Without this, fragment references fall back to `any`. With it, the compiler emits:

- `FooQuery$variables` / `FooQuery$data` / `FooQuery$rawResponse`
- `FooFragment$key` (opaque fragment reference)
- `FooFragment$data`

The Babel plugin needs the same directory. Add it to the plugin options:

```json
{
  "plugins": [["relay", { "artifactDirectory": "./src/__generated__" }]]
}
```

Alias the directory in the module resolver so that imports do not use long relative paths.

Your `fetchFn` works with raw `GraphQLResponse` from `relay-runtime`; the typed surface is the hook output.

---

## 14. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `Cannot read property 'text' of undefined` in fetchFn | Using `request.query` instead of `request.text` | Use `request.text` (or `request.id` for persisted). |
| Subscriptions throw `NetworkError: no subscribe function` | `subscribeFn` not passed to `Network.create` | Pass it as the second arg. |
| File upload sent as JSON `[object File]` | Manually set `Content-Type: multipart/form-data` | Omit the header — browser adds boundary. |
| Server receives empty `variables` on upload | Forgot to `JSON.stringify` variables before appending to FormData | `form.append('variables', JSON.stringify(variables))`. |
| Persisted query server returns "unknown doc_id" | Dev build uploaded a new hash to a stale server map | Re-run compiler, redeploy map, or fall back to sending `text` in dev. |
| `@defer` payloads never render second chunk | Returning a Promise instead of Observable from fetchFn | Use `Observable.create` and `sink.next` per part. |
| `meros` returns a single `Response` instead of iterable | Server didn't send `Content-Type: multipart/mixed` | Fix server; confirm `Accept` header from client. |
| Fragment refs typed as `any` | Missing `artifactDirectory` | Set it and re-run compiler. |
| `usePaginationFragment` complains about connection shape | Server missing `pageInfo`/`edges`/`cursor` | Conform to connection spec exactly. |
| `node(id)` refetch returns wrong type | IDs not globally unique | Encode type into id (e.g. base64 of `Type:local`). |
| Mutation `onCompleted` gets `errors` but UI shows no error | `data` was non-null so Relay ignored partial errors | Read `errors` in `onCompleted(data, errors)` yourself. |
| WebSocket reconnects lose auth | `connectionParams` was a static object | Use a function so it re-evaluates on reconnect. |
| Batching breaks file uploads | Uploads sharing a batch request | Short-circuit: skip the queue when `uploadables` is truthy. |
| 401 loop on token expiry | fetchFn not refreshing before retry | Refresh, then retry once; give up on second 401. |
| `request.id` is null in prod | `persistConfig` not set, or compiler run without it | Add `persistConfig` and re-run `relay-compiler`. |
| Subscription never unsubscribes | `Observable.create` callback didn't return cleanup | Return the `wsClient.subscribe` disposer. |
| `cacheConfig.force` ignored | fetchFn shares responses from an in-memory cache | Bypass your cache when `cacheConfig.force === true`. |
| `@defer` data never appears although parts arrive | Parts use an `incremental` array or lack `path`/`label` | Send each part as `{ data, path, label }`, or split `incremental` in `fetchFn`. |
| `invalid incremental payload` error | Part has `path` without `label`, or `label` without `path` | Send both fields, or neither for the initial payload. |
| Babel plugin cannot find artifacts | Compiler uses `artifactDirectory` and the plugin does not | Set `artifactDirectory` in the plugin options too. |
| Pagination breaks after renaming connection fields | Compiler and runtime use different connection names | Set `schemaConfig.connectionInterface` and call `ConnectionInterface.inject` with the same values. |

---

## Sources

- [Network Layer — relay.dev](https://relay.dev/docs/guides/network-layer/)
- [Persisted Queries — relay.dev](https://relay.dev/docs/guides/persisted-queries/)
- [GraphQL Server Specification — relay.dev](https://relay.dev/docs/guides/graphql-server-specification/)
- [Client Schema Extensions — relay.dev](https://relay.dev/docs/guides/client-schema-extensions/)
- [Type Emission — relay.dev](https://relay.dev/docs/guides/type-emission/)
- [GraphQL Subscriptions — relay.dev](https://relay.dev/docs/guided-tour/updating-data/graphql-subscriptions/)
- [graphql-ws recipes](https://the-guild.dev/graphql/ws/recipes)
- [meros (multipart parser)](https://github.com/maraisr/meros)
- [meros + relay + helix example](https://github.com/maraisr/meros/blob/aba7ad1be69bcd7e4ee76304d5079fb0e2933b83/examples/relay-with-helix/server.ts)
