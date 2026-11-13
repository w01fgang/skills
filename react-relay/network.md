# Network Layer & Server Integration

Relay requires an object that implements the `INetwork` interface when you create a Relay Environment. The environment uses this network layer to execute queries, mutations and (if your server supports them) subscriptions. This allows you to use whatever transport (HTTP, WebSockets, etc) and authentication is most appropriate for your application. This reference covers how to build that layer and the assumptions Relay makes about the GraphQL server.

---

## 1. `Network.create` — the entry point

The easiest way to create a network layer is the `Network.create` helper from the `relay-runtime` package. Pass it a function that fetches the results of an operation (query/mutation/etc) and returns its results as a Promise:

```javascript
import {
  Environment,
  Network,
  RecordSource,
  Store,
} from 'relay-runtime';

// Define a function that fetches the results of an operation (query/mutation/etc)
// and returns its results as a Promise:
function fetchQuery(
  operation,
  variables,
  cacheConfig,
  uploadables,
) {
  return fetch('/graphql', {
    method: 'POST',
    headers: {
      // Add authentication and other headers here
      'content-type': 'application/json'
    },
    body: JSON.stringify({
      query: operation.text, // GraphQL text from input
      variables,
    }),
  }).then(response => {
    return response.json();
  });
}

// Create a network layer from the fetch function
const network = Network.create(fetchQuery);
const store = new Store(new RecordSource())

const environment = new Environment({
  network,
  store
  // ... other options
});

export default environment;
```

This is a basic example. Features like `@stream`, `@defer` or Persisted Queries require additional logic in your `fetchQuery` function.

The network layer is the place to customize data fetching behavior. For example, it can add network level caching, telemetry or support for uploading form data for mutations.

---

## 2. The fetch function arguments

| Arg | What it is |
|-----|-----------|
| `operation` | The operation (request parameters). Use `operation.text` (the GraphQL text) or `operation.id` (the persisted query id). `operation.name` is the operation name. |
| `variables` | Variables for this operation. |
| `cacheConfig` | `{ force?: boolean, poll?: number, liveConfigId?: string, metadata?: object, transactionId?: string }`. If `force` is true, the query is issued unconditionally, regardless of the state of any configured response cache. `poll` makes a query live-update by polling at the specified interval in milliseconds. |
| `uploadables` | An `UploadableMap`: an object whose values are `File` or `Blob`. |

`fetchQuery` takes a `networkCacheConfig` option with a `force` field. `force` defaults to true.

---

## 3. Relay's `Observable`

In Relay, observables are a partial implementation of RxJS Observables. Observables differ from promises: if the data in an observable is already loaded, you can access it synchronously.

A fetch function can wrap a Promise with `Observable.from`:

```js
function fetchFunction(params, variables) {
  const response = fetch("http://my-graphql/api", {
    method: "POST",
    headers: [["Content-Type", "application/json"]],
    body: JSON.stringify({
      query: params.text,
      variables,
    }),
  });

  return Observable.from(response.then((data) => data.json()));
};
```

---

## 4. Persisted queries

The Relay compiler supports persisted queries. They are useful because:

- The client operation text becomes an md5 hash, which is usually shorter than the real query string. This saves upload bytes from the client to the server.
- The server can allowlist queries, which improves security by restricting the operations that a client can execute.

### Client compiler config (`package.json`)

In the `relay` configuration section of your `package.json`, specify `persistConfig`:

```
"scripts": {
  "relay": "relay-compiler",
  "relay-persisting": "node relayLocalPersisting.js"
},
"relay": {
  "src": "./src",
  "schema": "./schema.graphql",
  "persistConfig": {
    "url": "http://localhost:2999",
    "params": {}
  }
}
```

`persistConfig` does the following:

1. It converts all query and mutation operation texts to md5 hashes. Without `persistConfig`, a generated `ConcreteRequest` has `"id": null` and the query string in `"text"`. With `persistConfig`, `"id"` is the md5 hash of the query text and `"text"` is `null`.
2. It sends an HTTP POST request with a `text` parameter to the specified `url`. The `params` option adds more request body parameters.

### Local persisted queries

With this config, the compiler generates a local JSON file that contains a map of `operation_id => full operation text`:

```
"scripts": {
  "relay": "relay-compiler"
},
"relay": {
  "src": "./src",
  "schema": "./schema.graphql",
  "persistConfig": {
    "file": "./persisted_queries.json",
    "algorithm": "MD5" // this can be one of MD5, SHA256, SHA1
  }
}
```

Ship this file to your server at deploy time, so the server knows all the queries it can receive. If you do not do that, implement the [Automatic Persisted Queries handshake](https://www.apollographql.com/docs/apollo-server/performance/apq/).

Tradeoffs of the Automatic Persisted Queries handshake:

- If the server's persisted query datastore gets wiped, it recovers automatically through the client's requests.
- A cache miss costs an extra round trip to the server.
- You ship the `persisted_queries.json` file to the browser, which increases the bundle size.

### `persistConfig` options

`persistConfig` converts the text of every query and mutation into an id. The same options exist on v20.1 and v21.

| Key | Meaning |
|---|---|
| `url` | The compiler sends an HTTP POST request with a `text` parameter to this URL. |
| `params` | Extra request body parameters that the compiler adds to the POST request. |
| `file` | Path of a local JSON file. The compiler writes the map `id → operation text` to it. |
| `algorithm` | Hash for the local file: `MD5`, `SHA256` or `SHA1`. |

The compiler config schema at tags v20.1.1 and v21.0.1 lists more keys.

- Remote: `headers`, `concurrency`, `includeQueryText`.
- Local: `include_query_text` (snake case).
- A multi-project config names the option `persist`.

### Example `relayLocalPersisting.js`

This persist server saves query text to the `queryMap.json` file.

```javascript
const http = require('http');
const crypto = require('crypto');
const fs = require('fs');

function md5(input) {
  return crypto.createHash('md5').update(input).digest('hex');
}

class QueryMap {
  constructor(fileMapName) {
    this._fileMapName = fileMapName;
    this._queryMap = new Map(JSON.parse(fs.readFileSync(this._fileMapName)));
  }

  _flush() {
    const data = JSON.stringify(Array.from(this._queryMap.entries()));
    fs.writeFileSync(this._fileMapName, data);
  }

  saveQuery(text) {
    const id = md5(text);
    this._queryMap.set(id, text);
    this._flush();
    return id;
  }
}

const queryMap = new QueryMap('./queryMap.json');

async function requestListener(req, res) {
  if (req.method === 'POST') {
    const buffers = [];
    for await (const chunk of req) {
      buffers.push(chunk);
    }
    const data = Buffer.concat(buffers).toString();
    res.writeHead(200, {
      'Content-Type': 'application/json'
    });
    try {
      if (req.headers['content-type'] !== 'application/x-www-form-urlencoded') {
        throw new Error(
          'Only "application/x-www-form-urlencoded" requests are supported.'
        );
      }
      const text = new URLSearchParams(data).get('text');
      if (text == null) {
        throw new Error('Expected to have `text` parameter in the POST.');
      }
      const id = queryMap.saveQuery(text);
      res.end(JSON.stringify({"id": id}));
    } catch (e) {
      console.error(e);
      res.writeHead(400);
      res.end(`Unable to save query: ${e}.`);
    }
  } else {
    res.writeHead(400);
    res.end("Request is not supported.")
  }
}

const PORT = 2999;
const server = http.createServer(requestListener);
server.listen(PORT);

console.log(`Relay persisting server listening on ${PORT} port.`);
```

This example writes the complete query map file to `./queryMap.json`. To use it, update `package.json`:

```
"scripts": {
  "persist-server": "node ./relayLocalPersisting.js",
  "relay": "relay-compiler"
}
```

### Network layer changes

Modify the network layer fetch implementation to pass an ID parameter in the POST body (for example `doc_id`):

```javascript
function fetchQuery(operation, variables) {
  return fetch('/graphql', {
    method: 'POST',
    headers: {
      'content-type': 'application/json'
    },
    body: JSON.stringify({
      doc_id: operation.id, // NOTE: pass md5 hash to the server
      // query: operation.text, // this is now obsolete because text is null
      variables,
    }),
  }).then(response => {
    return response.json();
  });
}
```

### Executing persisted queries on the server

The server must look up the query text that corresponds to each ID. Typically you save the `queryMap.json` file to a database or other storage and retrieve the text for the ID that a client sends. The `relayLocalPersisting.js` implementation can also save queries directly to the database or other storage.

- Universal applications (client and server code in one project): place the query map file in a common location that both the client and the server can access.
- Separate client and server projects, compile time push: add an npm run script that pushes the query map at compile time to a location your server can access.

```javascript
"scripts": {
  "push-queries": "node ./pushQueries.js",
  "persist-server": "node ./relayLocalPersisting.js",
  "relay": "relay-compiler && npm run push-queries"
}
```

In `./pushQueries.js` you can `git push` to your server repo or save the query maps to a database.

- Run time push: push the query maps to the server at runtime, without the server knowing the query IDs at the start. The client optimistically sends a query ID to the server. The server then requests the full query text from the client and caches the query map for later requests. This approach is more complex, because the client and server must interact to exchange the query maps.

With `express-graphql` and access to the query map file, import it and match with the `persistedQueries` middleware from [express-graphql-persisted-queries](https://github.com/kyarik/express-graphql-persisted-queries):

```javascript
import express from 'express';
import {graphqlHTTP} from 'express-graphql';
import {persistedQueries} from 'express-graphql-persisted-queries';
import queryMap from './path/to/queryMap.json';

const app = express();

app.use(
  '/graphql',
  persistedQueries({
    queryMap,
    queryIdKey: 'doc_id',
  }),
  graphqlHTTP({schema}),
);
```

### `persistConfig` with `--watch`

Use `persistConfig` and `--watch` together to continuously generate the query map files. This only makes sense for universal applications, where client and server code are in a single project and run together on localhost during development. For the server to pick up changes to `queryMap.json`, set up server side hot-reloading.

---

## 5. File uploads via `uploadables`

The fetch function receives `uploadables` as its fourth argument. An `UploadableMap` is an object whose values are `File` or `Blob`. A mutation takes an optional `uploadables` map in its config. Use the fetch function to support uploading form data for mutations.

---

## 6. Subscriptions — `subscribeFn`

Configure the network layer to handle subscriptions. Pass the subscribe function as the second argument of `Network.create`:

```javascript
const network = Network.create(fetchQuery, subscribe);
```

Usually GraphQL subscriptions are communicated over [WebSockets](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API). This example uses [graphql-ws](https://github.com/enisdenjo/graphql-ws):

```javascript
import {
    ...
    Network,
    Observable
} from 'relay-runtime';
import { createClient } from 'graphql-ws';

const wsClient = createClient({
  url:'ws://localhost:3000',
});

const subscribe = (operation, variables) => {
  return Observable.create((sink) => {
    return wsClient.subscribe(
      {
        operationName: operation.name,
        query: operation.text,
        variables,
      },
      sink,
    );
  });
}

const network = Network.create(fetchQuery, subscribe);
```

The legacy [subscriptions-transport-ws](https://github.com/apollographql/subscriptions-transport-ws) library also works:

```javascript
import {
    ...
    Network,
    Observable
} from 'relay-runtime';
import { SubscriptionClient } from 'subscriptions-transport-ws';

const subscriptionClient = new SubscriptionClient('ws://localhost:3000', {
  reconnect: true,
});

const subscribe = (request, variables) => {
  const subscribeObservable = subscriptionClient.request({
    query: request.text,
    operationName: request.name,
    variables,
  });
  // Important: Convert subscriptions-transport-ws observable type to Relay's
  return Observable.from(subscribeObservable);
};

const network = Network.create(fetchQuery, subscribe);
```

Use `useSubscription` or `requestSubscription` to create a subscription:

```js
import type {Environment} from 'react-relay';
import type {FeedbackLikeSubscribeData} from 'FeedbackLikeSubscription.graphql';

const {graphql, useSubscription} = require('react-relay');
const {useMemo} = require('React');

function useFeedbackSubscription(
  input: FeedbackLikeSubscribeData,
) {
  const config = useMemo(() => ({
    subscription: graphql`
      subscription FeedbackLikeSubscription(
        $input: FeedbackLikeSubscribeData!
      ) {
        feedback_like_subscribe(data: $input) {
          feedback {
            like_count
          }
        }
      }
    `,
    variables: {input},
  }), [input]);

  return useSubscription(config);
}
```

`useSubscription` takes a `GraphQLSubscriptionConfig` object with these fields:

| Field | Purpose |
|---|---|
| `subscription` | The GraphQL literal that contains the subscription. |
| `variables` | The variables with which to establish the subscription. |
| `onNext` | Runs when a subscription payload is received. It receives the subscription response (stopping at fragment spread boundaries). |
| `onError` | Runs when the subscription errors. It receives the error. |
| `onCompleted` | Runs when the server ends the subscription. |
| `updater` | Gives you full control over how to update the store. |

- Memoize the config object. Otherwise `useSubscription` disposes the subscription and re-establishes it with every render.
- Relay establishes the subscription when the hook commits. Relay does not establish it during the render phase.
- Spread the fragments of the components that you want to refresh in the subscription selection. This keeps those components in a consistent state.
- Declarative mutation directives and `@deleteRecord` work in subscriptions.

---

## 7. `@defer` / `@stream`

- `@stream`, `@defer` and persisted queries require additional logic in your fetch function (see section 1).
- `deferDeduplicatedFields: true` in the `Environment` config stops Relay from throwing an error when it receives missing fields in a deferred response (v21 only; absent in the v20.1.1 source). The latest `@defer` spec proposal does not send duplicate fields in deferred responses. Relay does not yet support that proposal. The option lets you transform responses into a format that Relay accepts.

---

## 8. GraphQL server requirements for Relay

Relay makes two core assumptions about a GraphQL server. It provides:

1. A mechanism for refetching an object.
2. A description of how to page through connections.

### 8.1 Node interface (Global Object Identification)

The `Node` interface and the `node` field on the root query type expose refetching to Relay:

```graphql
interface Node {
  id: ID!
}

type Query {
  node(id: ID!): Node
}
```

The `Node` interface contains a single field, `id`, which is an `ID!`. The `node` root field takes a single argument, an `ID!`, and returns a `Node`. If you pass the `id` returned in that field to the `node` field, you get the object back.

The `Node` interface and `node` field assume globally unique IDs. A system without globally unique IDs can usually synthesize them by combining the type with the type-specific ID.

IDs are opaque. The only thing to pass to the `id` argument on `node` is the unaltered result of querying `id` on some object in the system. A base64 string is a useful convention in GraphQL to remind viewers that the string is an opaque identifier.

### 8.2 Connection specification (pagination)

List fields that support pagination follow the connection model:

```graphql
type ShipConnection {
  edges: [ShipEdge]
  pageInfo: PageInfo!
}

type ShipEdge {
  cursor: String!
  node: Ship
}

type PageInfo {
  hasNextPage: Boolean!
  hasPreviousPage: Boolean!
  startCursor: String
  endCursor: String
}
```

The connection field takes the `first` and `after` arguments to slice and paginate. Each edge exposes a `cursor`, which is an opaque string. `PageInfo` tells the client whether it reached the end of the connection (`hasNextPage`).

If the server's implementation of the Connection Spec differs from the default interface, configure the Relay Runtime to expect the connection type and field names of your schema. Update the global `ConnectionInterface` instance exported by Relay. Also update the Relay compiler config with the same values at the path `schemaConfig.connectionInterface`.

```ts
import { ConnectionInterface } from 'relay-runtime';

// Note: This must match the values configured in the Relay compiler config.
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

---

## 9. Client schema extensions (local-only state)

The Relay Compiler supports client-side extensions of the schema, which define local fields and types. Create a `.graphql` file inside your `--src` directory, for example `./src/clientSchema.graphql`. Reference this file in the `"schemaExtensions"` of your Relay config, directly or through its folder.

For example, a new type called `Note`:

```graphql
type Note {
  id: ID!
  title: String
  body: String
}
```

And an extension of the server schema type `User` with a list of `Note`, called `notes`:

```graphql
extend type User {
  notes: [Note]
}
```

Accessing local data is the same as querying your GraphQL server. The query must include at least one server field. The field can come from the server schema, or it can be schema agnostic, like an introspection field (for example `__typename`).

```javascript
// Example.js
import * as React from 'react';
import { useLazyLoadQuery, graphql } from 'react-relay';

const Example = (props) => {
  const data = useLazyLoadQuery(graphql`
    query ExampleQuery {
      viewer {
        id
        name
        notes {
          id
          title
          body
        }
      }
    }
  `, {});
  // ...
}
```

Write local state with an `updater` function. `commitLocalUpdate` fits this case, because writes to local state usually run outside of a mutation.

---

## 10. Type emission

The Relay Compiler emits type information for your language of choice. The emitted types are in the artifacts that `relay-compiler` generates. Examples are `ExampleQuery$variables` and `ExampleQuery$data`.

By default, strict fragment reference type information is not emitted. Fragment references are typed as `any`. To enable it, tell the compiler to store all artifacts in a single directory with `artifactDirectory` in the compiler configuration:

```
{
  // package.json
  "relay": {
    "artifactDirectory": "./src/__generated__",
    ...
  },
  ...
}
```

Also tell the babel plugin in your `.babelrc` config where to look for the artifacts:

```json
{
  "plugins": [
    ["relay", { "artifactDirectory": "./src/__generated__" }]
  ]
}
```

Alias this directory in your module resolution configuration, so that source files do not need relative paths.

---

## 11. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Fragment refs typed as `any` | Missing `artifactDirectory` | Set it and re-run compiler. |
| `node(id)` refetch returns wrong type | IDs not globally unique | Combine the type with the type-specific ID. |
| `request.id` is null in prod | `persistConfig` not set, or compiler run without it | Add `persistConfig` and re-run `relay-compiler`. |
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
