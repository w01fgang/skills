# React Relay Hooks

Reference for the React Relay hooks. All examples are hooks-only. They use Flow type syntax, as the Relay docs do.

Use every hook inside a component tree wrapped with a `RelayEnvironmentProvider`. Data-fetching hooks use `Suspense` for loading states and throw errors that an Error Boundary can catch.

---

## RelayEnvironmentProvider

Sets a Relay environment in React Context. Render 1 instance at the very root of the application to set the environment for the whole application.

```js
const React = require('React');
const {
  Store,
  RecordSource,
  Environment,
  Network,
  Observable,
} = require("relay-runtime");

const {RelayEnvironmentProvider} = require('react-relay');

/**
 * Custom fetch function to handle GraphQL requests for a Relay environment.
 *
 * This function is responsible for sending GraphQL requests over the network and returning
 * the response data. It can be customized to integrate with different network libraries or
 * to add authentication headers as needed.
 *
 * @param {RequestParameters} params - The GraphQL request parameters to send to the server.
 * @param {Variables} variables - Variables used in the GraphQL query.
 */
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

/**
 * Creates a new Relay environment instance for managing (fetching, storing) GraphQL data.
 */
function createEnvironment() {
  const network = Network.create(fetchFunction);
  const store = new Store(new RecordSource());
  return new Environment({ store, network });
}

const environment = createEnvironment();

function Root() {
  return (
    <RelayEnvironmentProvider environment={environment}>
      <App />
    </RelayEnvironmentProvider>
  );
}

module.exports = Root;
```

Props:

- `environment` — the Relay environment to set in React Context. Any Relay Hook in a descendant of the provider uses this environment.

`useLazyLoadQuery` throws an error when it renders outside a `RelayEnvironmentProvider`.

---

## useFragment

Reads fragment data from the Relay store with a fragment reference.

```js
import type {UserComponent_user$key} from 'UserComponent_user.graphql';

const React = require('React');

const {graphql, useFragment} = require('react-relay');

type Props = {
  user: UserComponent_user$key,
};

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
      <div>
        <img src={data.profile_picture?.uri} />
      </div>
    </>
  );
}
```

### Arguments

- `fragment` — GraphQL fragment specified with a `graphql` template literal.
- `fragmentReference` — an opaque Relay object that Relay uses to read the data for the fragment from the store. It contains the information about which object instance the data comes from.
  - Import the type of the fragment reference from the generated Flow types, from the file `<fragment_name>.graphql.js`. Use it to declare the type of `Props`. The name of the type is `<fragment_name>$key`. The lint rule of `eslint-plugin-relay` enforces that the type of the fragment reference prop is declared.

### Return value

- `data` — object with the data read from the Relay store. The object matches the shape of the fragment. The Flow type of `data` matches this shape too.

### Behavior

- The component subscribes to updates of the fragment data. When the data of this object changes anywhere in the app, the component re-renders with the latest data.
- The component suspends if any data for the fragment is missing and a parent query is fetching that data.

---

## usePreloadedQuery

Reads data that an earlier call to `loadQuery`, or `useQueryLoader`, fetched. This implements the "render-as-you-fetch" pattern:

- Call the `loadQuery` callback from `useQueryLoader`. The callback stores a query reference in React state.
- You can also call the imported `loadQuery` directly. It returns a query reference. Store the reference in state or in a React ref, and call `dispose()` on it when you stop using it.
- In the render method, consume the query reference with `usePreloadedQuery()`. The call suspends if the query is pending, throws an error if the query failed, and otherwise returns the query results.
- The docs encourage this pattern over `useLazyLoadQuery()`. It can fetch data earlier and does not block rendering.

```js
import type {AppQueryType} from 'AppQueryType.graphql';

const React = require('React');

const {graphql, useQueryLoader, usePreloadedQuery} = require('react-relay');

const AppQuery = graphql`
  query AppQuery($id: ID!) {
    user(id: $id) {
      name
    }
  }
`;

type Props = {
  initialQueryRef: PreloadedQuery<AppQueryType>,
};

function NameLoader(props) {
  const [queryReference, loadQuery] = useQueryLoader(
    AppQuery,
    props.initialQueryRef, /* e.g. provided by router */
  );

  return (<>
    <Button
      onClick={() => loadQuery({id: '4'})}
      disabled={queryReference != null}
    >
      Reveal your name!
    </Button>
    <Suspense fallback="Loading...">
      {queryReference != null
        ? <NameDisplay queryReference={queryReference} />
        : null
      }
    </Suspense>
  </>);
}

function NameDisplay({ queryReference }) {
  const data = usePreloadedQuery(AppQuery, queryReference);

  return <h1>{data.user?.name}</h1>;
}
```

### Arguments

- `query` — GraphQL query specified with a `graphql` template literal.
- `preloadedQueryReference` — a `PreloadedQuery` query reference from `useQueryLoader` or from `loadQuery()`.

### Return value

- `data` — object with the data read from the Relay store. The object matches the shape of the query. The Flow type of `data` matches this shape too.

### Pitfalls

- Guard against a `null` query reference before you render the consumer. On v21 the Flow overload accepts `null` and the hook returns `null` (`usePreloadedQuery.js`). On v20 a `null` ref throws, and the TypeScript type on both versions requires a non-null ref.

---

## useLazyLoadQuery

Fetches a GraphQL query during render. The hook can trigger multiple nested or waterfalling round trips if you use it without caution. It waits until render to start a data fetch, although the fetch can usually start sooner, so it degrades performance. Prefer `usePreloadedQuery`.

```js
const React = require('React');

const {graphql, useLazyLoadQuery} = require('react-relay');

function App() {
  const data = useLazyLoadQuery(
    graphql`
      query AppQuery($id: ID!) {
        user(id: $id) {
          name
        }
      }
    `,
    {id: 4},
    {fetchPolicy: 'store-or-network'},
  );

 return <h1>{data.user?.name}</h1>;
}
```

### Arguments

- `gqlQuery` — GraphQL query specified with a `graphql` template literal.
- `variables` — object with the variable values for the query. The variables match the GraphQL variables declared in the query.
- `options` — optional options object.

### Options

| Option | Default | Behavior |
|---|---|---|
| `fetchPolicy` | `"store-or-network"` | See "Fetch policies". |
| `fetchKey` | none | Forces a re-evaluation of the current query and variables when the component re-renders, even when the variables did not change and the component did not remount. This works like a different `key` on a React component. If `fetchKey` differs from the previous render, Relay re-evaluates the query against the store. It can refetch, depending on `fetchPolicy` and the state of the cache. |
| `networkCacheConfig` | `{force: true}` | Cache config options for the network layer. The network layer can contain an additional query response cache that reuses network responses for identical queries. Pass `{force: true}` to bypass this cache. |
| `UNSTABLE_renderPolicy` | none | Undocumented option. |

### Fetch policies

- `store-or-network` (default) — reuses locally cached data. Sends a network request only if any data for the query is missing. A fully cached query makes no network request.
- `store-and-network` — reuses locally cached data and always sends a network request.
- `network-only` — does not reuse locally cached data and always sends a network request.
- `store-only` — reuses locally cached data and never sends a network request. The caller fetches the query. The policy can also read data that is entirely [local](https://relay.dev/docs/guided-tour/updating-data/local-data-updates).

### Return value

- `data` — object with the data read from the Relay store. The object matches the shape of the query. The Flow type of `data` matches this shape too.

### Behavior

- Render the hook under a `RelayEnvironmentProvider`. Otherwise the hook throws an error.
- The hook fetches and renders the data of the query. It can suspend while the network request is in flight, depending on the `fetchPolicy` and on whether cached data is available. If the hook suspends, a `Suspense` ancestor must wrap the component to show the loading state.
- The component subscribes to updates of the query data. When the data changes anywhere in the app, the component re-renders with the latest data.
- After the component commits, a re-render does not fetch the query again.
  - A re-render with different query variables fetches the query again with the new variables.
  - An unmount followed by a mount refetches the current query and variables, depending on the `fetchPolicy` and the state of the cache.
- A failed request throws an error during render. Catch it with an Error Boundary and retry (see "Retrying after an error").

---

## useQueryLoader

Loads and retains queries. It keeps a query reference in state and disposes of it when the component is disposed or the reference is not accessible through state.

The hook works with `usePreloadedQuery` to implement the "render-as-you-fetch" pattern.

```js
import type {PreloadedQuery} from 'react-relay';

const {useQueryLoader, usePreloadedQuery} = require('react-relay');

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

  if (queryReference == null) {
    return (
      <Button onClick={() => loadQuery({})}> Click to reveal the name </Button>
    );
  }

  return (
    <>
      <Button onClick={disposeQuery}>
        Click to hide the name and dispose the query.
      </Button>
      <React.Suspense fallback="Loading">
        <NameDisplay queryReference={queryReference} />
      </React.Suspense>
    </>
  );
}

function NameDisplay({ queryReference }) {
  const data = usePreloadedQuery(AppQuery, queryReference);

  return <h1>{data.user?.name}</h1>;
}
```

### Arguments

- `query` — GraphQL query specified with a `graphql` template literal.
- `initialQueryRef` — optional. An initial `PreloadedQuery` that is the initial value of the `queryReference` in state.

### Return value

A tuple:

- `queryReference` — the query reference, or `null`.
- `loadQuery(variables, options)` — loads a query. The result is available as `queryReference`. If a previous query was loaded, it disposes of it. Do not call it during React's render phase.
  - `variables` — the variables for the query.
  - `options.fetchPolicy` — optional. `"store-or-network"` (default), `"store-and-network"` or `"network-only"`. See the fetch policies of `useLazyLoadQuery`.
  - `options.networkCacheConfig` — optional. Default `{force: true}`.
- `disposeQuery()` — sets `queryReference` to `null` and calls `.dispose()` on it. Type `() => void`. Do not call it during React's render phase.

### Behavior

- `loadQuery` fetches data when you pass a query. It fetches the data and the query when you pass a preloadable concrete request. When both are available, Relay writes the data to the store. This differs from `preloadQuery_DEPRECATED`, which writes data to the store only when `usePreloadedQuery` receives the query.
- The Relay store retains the query reference. The data stays out of garbage collection until `.dispose()` runs on the reference.

---

## loadQuery (imperative)

Designed to work with `usePreloadedQuery()` for the "render-as-you-fetch" pattern. References from `loadQuery` leak data into the Relay store unless `.dispose()` runs on them when nothing references them. Prefer `useQueryLoader`, which disposes of query references for you.

```js
const MyEnvironment = require('MyEnvironment');
const {loadQuery} = require('react-relay');

const query = graphql`
  query AppQuery($id: ID!) {
    user(id: $id) {
      name
    }
  }
`;

// Note: you should generally not call loadQuery at the top level.
// Instead, it should be called in response to an event (such a route navigation,
// click, etc.).
const queryReference = loadQuery(
  MyEnvironment,
  query,
  {id: '4'},
  {fetchPolicy: 'store-or-network'},
);

// later: pass queryReference to usePreloadedQuery()
// Note that query reference should have .dispose() called on them,
// which is missing in this example.
```

| Argument | Behavior |
|---|---|
| `environment` | The Relay Environment instance that runs the request. Inside a component, use the environment from `useRelayEnvironment`. |
| `query` | A `graphql` template literal, or a preloadable concrete request. Get a preloadable concrete request by requiring the file `<name-of-query>$Parameters.graphql`. Relay generates the `$Parameters` file only if the query has the `@preloadable` annotation. |
| `variables` | Object with the variable values for the query. |
| `options.fetchPolicy` | `"store-or-network"` (default), `"store-and-network"` or `"network-only"`. |
| `options.networkCacheConfig` | Default `{force: true}`. |
| `environmentProviderOptions` | Optional. Options passed to an `environmentProvider` used in `prepareSurfaceEntryPoint.js`. |

- The return value is a query reference with the property `dispose`. `dispose` releases the query reference from the store, so Relay can garbage collect its data.
- The docs state that only `dispose` is a stable property of the return value. The format of the other properties is unstable. Pass the result to `usePreloadedQuery()`.
- Once the query and the data are available, Relay writes the data to the store.
- Call `loadQuery` from an event handler or router callback. The docs state that `loadQuery` throws during render. The v20.1.1 and v21.0.1 source has no render-phase check, so a call in render creates a new undisposed reference on every render.

---

## Retrying after an error

`usePreloadedQuery` and `useLazyLoadQuery` throw when the request fails. Error Boundaries are components that implement the static `getDerivedStateFromError` method. A retry needs a new request. The retry trigger depends on the query hook.

### When using `useQueryLoader` / `loadQuery`

Call `loadQuery` again and pass the new query reference to `usePreloadedQuery`.

```js
/**
 * ErrorBoundaryWithRetry.react.js
 */

const React = require('React');

// NOTE: This is NOT actual production code;
// it is only used to illustrate example
class ErrorBoundaryWithRetry extends React.Component<Props, State> {
  state = {error: null};

  static getDerivedStateFromError(error): State {
    return {error: error};
  }

  _retry = () => {
    // This ends up calling loadQuery again to get and render
    // a new query reference
    this.props.onRetry();
    this.setState({
      // Clear the error
      error: null,
    });
  }

  render() {
    const {children, fallback} = this.props;
    const {error} = this.state;
    if (error) {
      if (typeof fallback === 'function') {
        return fallback({error, retry: this._retry});
      }
      return fallback;
    }
    return children;
  }
}
```

```js
/**
 * App.react.js
 */

const ErrorBoundaryWithRetry = require('ErrorBoundaryWithRetry');
const React = require('React');

const MainContent = require('./MainContent.react');

const query = require('__generated__/MainContentQuery.graphql');

// NOTE: This is NOT actual production code;
// it is only used to illustrate example
function App(props) {
  // E.g., initialQueryRef provided by router
  const [queryRef, loadQuery] = useQueryLoader(query, props.initialQueryRef);

  return (
    <ErrorBoundaryWithRetry
      // On retry we call loadQuery again, which will update
      // the value of queryRef from useQueryLoader with a new
      // fresh query reference
      onRetry={() => loadQuery(/* ... */)}
      fallback={({error, retry}) =>
        <>
          <ErrorUI error={error} />
          {/* Render a button to retry; this will attempt to re-render the
          content inside the boundary, i.e. the query component */}
          <Button onPress={retry}>Retry</Button>
        </>
      }>
      {/* The value of queryRef will be updated after calling
      loadQuery again */}
      <MainContent queryRef={queryRef} />
    </ErrorBoundaryWithRetry>
  );
}

/**
 * MainContent.react.js
 */
function MainContent(props) {
  const data = usePreloadedQuery(
    graphql`...`,
    props.queryRef
  );

  return (/* ... */);
}
```

- When an error occurs, the boundary renders the provided `fallback`.
- `retry` clears the error and calls `loadQuery` again. This fetches the query again and provides a new query reference for `usePreloadedQuery`. The component that uses `usePreloadedQuery` consumes the new reference and suspends if necessary on the new network request.

### When using `useLazyLoadQuery`

Re-mount and re-evaluate the query component by passing it a new `fetchKey`.

```js
/**
 * ErrorBoundaryWithRetry.react.js
 */

const React = require('React');

// NOTE: This is NOT actual production code;
// it is only used to illustrate example
class ErrorBoundaryWithRetry extends React.Component<Props, State> {
  state = {error: null, fetchKey: 0};

  static getDerivedStateFromError(error): State {
    return {error: error, fetchKey: 0};
  }

  _retry = () => {
    this.setState(prev => ({
      // Clear the error
      error: null,
      // Increment and set a new fetchKey in order
      // to trigger a re-evaluation and refetching
      // of the query using useLazyLoadQuery
      fetchKey: prev.fetchKey + 1,
    }));
  }

  render() {
    const {children, fallback} = this.props;
    const {error, fetchKey} = this.state;
    if (error) {
      if (typeof fallback === 'function') {
        return fallback({error, retry: this._retry});
      }
      return fallback;
    }
    return children({fetchKey});
  }
}
```

```js
/**
 * App.react.js
 */

const ErrorBoundaryWithRetry = require('ErrorBoundaryWithRetry');
const React = require('React');

const MainContent = require('./MainContent.react');

// NOTE: This is NOT actual production code;
// it is only used to illustrate example
function App() {
  return (
    <ErrorBoundaryWithRetry
      fallback={({error, retry}) =>
        <>
          <ErrorUI error={error} />
          {/* Render a button to retry; this will attempt to re-render the
            content inside the boundary, i.e. the query component */}
          <Button onPress={retry}>Retry</Button>
        </>
      }>
      {({fetchKey}) => {
        // If we have retried, use the new `retryQueryRef` provided
        // by the Error Boundary
        return <MainContent fetchKey={fetchKey} />;
      }}
    </ErrorBoundaryWithRetry>
  );
}

/**
 * MainContent.react.js
 */
function MainContent(props) {
  const data = useLazyLoadQuery(
    graphql`...`,
    variables,
    {fetchKey: props.fetchKey}
  );

  return (/* ... */);
}
```

- `retry` clears the error and increments `fetchKey`. The new `fetchKey` re-renders the component that uses `useLazyLoadQuery`, which re-evaluates and refetches the query. `useLazyLoadQuery` starts a new network request and suspends.

### Errors in GraphQL responses

To show user-friendly messages from GraphQL errors, model the error information as part of the GraphQL schema. The docs recommend this approach. For example, expose a field that returns either the expected result or an Error object.

---

## Refreshing and refetching without Suspense

Calling `loadQuery(variables, {fetchPolicy: 'network-only'})` again refreshes a query. The call makes `usePreloadedQuery` suspend, which replaces the visible content with the `Suspense` fallback. To avoid the fallback, use `fetchQuery` and track the loading state yourself.

```js
/**
 * App.react.js
 */

const AppQuery = require('__generated__/AppQuery.graphql');

function App(props: Props) {
  const environment = useRelayEnvironment();
  const [queryRef, loadQuery] = useQueryLoader(
    AppQuery,
    props.appQueryRef /* initial query ref */
  );
  const [isRefreshing, setIsRefreshing] = useState(false)

  const refresh = useCallback(() => {
    if (isRefreshing) { return; }
    const {variables} = props.appQueryRef;
    setIsRefreshing(true);

    // fetchQuery will fetch the query and write
    // the data to the Relay store. This will ensure
    // that when we re-render, the data is already
    // cached and we don't suspend
    fetchQuery(environment, AppQuery, variables)
      .subscribe({
        complete: () => {
          setIsRefreshing(false);

          // *After* the query has been fetched, we call
          // loadQuery again to re-render with a new
          // queryRef.
          // At this point the data for the query should
          // be cached, so we use the 'store-only'
          // fetchPolicy to avoid suspending.
          loadQuery(variables, {fetchPolicy: 'store-only'});
        }
        error: () => {
          setIsRefreshing(false);
        }
      });
  }, [/* ... */]);

  return (
    <React.Suspense fallback="Loading query...">
      <MainContent
        isRefreshing={isRefreshing}
        refresh={refresh}
        queryRef={queryRef}
      />
    </React.Suspense>
  );
}
```

- `isRefreshing` is your own loading state. Use it to render a busy spinner inside `MainContent` without hiding `MainContent`.
- `fetchQuery` fetches the query and writes the data to the local Relay store. When the request completes, `loadQuery` obtains an updated `queryRef` for `usePreloadedQuery`.
- The data is already cached when `loadQuery` runs, so the `'store-only'` fetch policy avoids suspending and reads the cached data. The v21 docs use `'store-only'` with `loadQuery` in this pattern.

---

## useRefetchableFragment

Fetches and re-renders a fragment with different data.

```js
import type {CommentBody_comment$key} from 'CommentBody_comment.graphql';

const React = require('React');

const {graphql, useRefetchableFragment} = require('react-relay');


type Props = {
  comment: CommentBody_comment$key,
};

function CommentBody(props: Props) {
  const [data, refetch] = useRefetchableFragment(
    graphql`
      fragment CommentBody_comment on Comment
      @refetchable(queryName: "CommentBodyRefetchQuery") {
        body(lang: $lang) {
          text
        }
      }
    `,
    props.comment,
  );

  return (
    <>
      <p>{data.body?.text}</p>
      <Button
        onClick={() => {
          refetch({lang: 'SPANISH'}, {fetchPolicy: 'store-or-network'})
        }}
      >
        Translate Comment
      </Button>
    </>
  );
}

module.exports = CommentBody;
```

### Arguments

- `fragment` — GraphQL fragment specified with a `graphql` template literal. The fragment must have a `@refetchable` directive. Without it, the hook throws an error. `@refetchable` works on fragments declared on `Viewer` or `Query`, or on a type that implements `Node`.
  - You do not specify a refetch query. The `@refetchable` directive generates a query with the given `queryName`, and Flow types for it in the generated file `<queryName>.graphql.js`.
- `fragmentReference` — the fragment reference, as for `useFragment`.

### Return value

A tuple:

- `[0] data` — object with the data read from the Relay store. The object matches the shape of the fragment.
- `[1] refetch(variables, options)` — refetches the fragment with a potentially new set of variables.
  - `variables` — object with the new variable values for the `@refetchable` query. They match the GraphQL variables referenced in the fragment.
    - If the fragment key is optional, pass all non-optional variables, including, potentially, the ID of the object. Relay may have no existing variables to reuse.
    - If the fragment key is non-optional, specify only the variables that change. Omitted variables fall back to the value from the original parent query. `refetch({})` refetches with the original variables.
    - If the fragment key is non-optional, an `id` value for `$id` is optional unless the fragment refetches a different `id`.
  - `options` — optional.

| Option | Behavior |
|---|---|
| `fetchPolicy` | Determines if cached data is used and when to send a network request. See "Fetch policy by API". |
| `onComplete` | Called when the refetch request completes, including incremental data payloads. |

`refetch` returns a `disposable` object with a `dispose` function. `disposable.dispose()` cancels the refetch request.

### Pending state with `useTransition`

Without a transition, Relay uses Suspense while the new data loads, and the whole component shows the fallback. To keep the current data on screen until the new data arrives, mark the refetch as a transition. Wrap the state change in the function that the `useTransition` hook provides. React re-renders the component with `isPending` set to true while it waits. Put `setSearchString` outside the transition and `refetch` inside it, so React updates the search input at once.

```js
const {useState, useTransition} = React;

function ContactsList({viewer}) {
  const [isPending, startTransition] = useTransition();
  const [searchString, setSearchString] = useState('');
  const [data, refetch] = useRefetchableFragment(ContactsListFragment, viewer);
  const onSearchStringChanged = (value) => {
    setSearchString(value);
    startTransition(() => {
      refetch({search: value});
    });
  };
  return (
    <Card dim={true}>
      <h3>Contacts</h3>
      <SearchInput
        value={searchString}
        onChange={onSearchStringChanged}
        isPending={isPending}
      />
      {data.contacts.map(contact =>
        <ContactRow key={contact.id} contact={contact} />
      )}
    </Card>
  );
}
```

### Behavior

- The component subscribes to updates of the fragment data and re-renders with the latest data.
- The component suspends if any data for the fragment is missing and a parent query is fetching that data.
- `refetch` fetches the fragment again with the new variables. Provide only the variables that the fragment references.
- `refetch` re-renders the component. It can suspend, depending on the `fetchPolicy` and on whether cached data is available. If `refetch` causes suspension, a `Suspense` boundary must wrap the component.

---

## usePaginationFragment

Renders a fragment that uses a `@connection` and paginates over it.

```js
import type {FriendsList_user$key} from 'FriendsList_user.graphql';

const React = require('React');

const {graphql, usePaginationFragment} = require('react-relay');

type Props = {
  user: FriendsList_user$key,
};

function FriendsList(props: Props) {
  const {
    data,
    loadNext,
    loadPrevious,
    hasNext,
    hasPrevious,
    isLoadingNext,
    isLoadingPrevious,
    refetch, // For refetching connection
  } = usePaginationFragment(
    graphql`
      fragment FriendsListComponent_user on User
      @argumentDefinitions(
        count: { type: "Int", defaultValue: 5 }
        cursor: { type: "String" }
      )
      @refetchable(queryName: "FriendsListPaginationQuery") {
        name
        friends(first: $count, after: $cursor)
        @connection(key: "FriendsList_user_friends") {
          edges {
            node {
              name
              age
            }
          }
        }
      }
    `,
    props.user,
  );

  return (
    <>
      <h1>Friends of {data.name}:</h1>

      <List items={data.friends?.edges.map(edge => edge.node)}>
        {node => {
          return (
            <div>
              {node.name} - {node.age}
            </div>
          );
        }}
      </List>
      <Button onClick={() => loadNext(10)}>Load more friends</Button>
    </>
  );
}

module.exports = FriendsList;
```

### Arguments

- `fragment` — GraphQL fragment specified with a `graphql` template literal.
  - The fragment must have an `@connection` directive on a connection field. Without it, the hook throws an error.
  - The fragment must have a `@refetchable` directive. Without it, the hook throws an error. `@refetchable` works on fragments declared on `Viewer` or `Query`, or on a type that implements `Node`.
  - You do not specify a pagination query. The `@refetchable` directive generates a query with the given `queryName`, and Flow types for it in the generated file `<queryName>.graphql.js`.
- `fragmentReference` — the fragment reference, as for `useFragment`.

### Return value

Object with these properties:

- `data` — object with the data read from the Relay store. The object matches the shape of the fragment.
- `isLoadingNext` — `true` while a pagination request for the next items is in flight, including incremental data payloads.
- `isLoadingPrevious` — `true` while a pagination request for the previous items is in flight, including incremental data payloads.
- `hasNext` — `true` if more items exist in the forward direction.
- `hasPrevious` — `true` if more items exist in the backward direction.
- `loadNext(count, options)` — fetches more items in the forward direction.
- `loadPrevious(count, options)` — fetches more items in the backward direction.
- `refetch(variables, options)` — refetches the connection fragment with a potentially new set of variables.

### `loadNext` and `loadPrevious` options

| Argument | Behavior |
|---|---|
| `count` | Number of items to query for in the pagination request. |
| `options.onComplete` | Called when the request completes, including incremental data payloads. If an error occurs, `onComplete` receives an `Error` object as the first parameter. |

- Both functions return a `disposable` object. `disposable.dispose()` cancels the pagination request.
- `loadNext` and `loadPrevious` do not suspend the component that calls them. They set `isLoadingNext` or `isLoadingPrevious` to true while the request is in flight. The new items are added to the connection and the component re-renders.
- Pagination requests use the variables that fetched the connection originally, except the pagination variables. Changing other variables would query a different connection.

### `refetch`

- `variables` — new variable values for the `@refetchable` query. Specify only the variables that change. Omitted variables fall back to the value from the original parent query. `refetch({})` refetches with the original variables. An `id` value for `$id` is optional unless the fragment refetches a different `id`.
- `options.fetchPolicy` — see "Fetch policy by API".
- `options.onComplete` — called when the refetch request completes, including incremental data payloads.
- `refetch` returns a `disposable` object. `disposable.dispose()` cancels the refetch request.
- `refetch` re-renders the component and can suspend, depending on the `fetchPolicy` and on whether cached data is available. If it suspends, a `Suspense` boundary must wrap the component.

With `usePaginationFragment`, Relay inserts the `pageInfo` and `cursor` selections of the connection, so the fragment needs only `edges { node }`. This statement comes from the v21 docs; the v20 docs omit it.

### Bi-directional pagination

Connections also allow pagination in the backward direction. Use the `before` and `last` connection arguments along with `after` and `first`. The APIs for both directions are the same and have different names. `usePaginationFragment` exposes both from a single call, so both directions can paginate at the same time in the same component.

```js
import type {FriendsListComponent_user$key} from 'FriendsListComponent_user.graphql';

const React = require('React');
const {Suspense} = require('React');

const {graphql, usePaginationFragment} = require('react-relay');

type Props = {
  userRef: FriendsListComponent_user$key,
};

function FriendsListComponent(props: Props) {
  const {
    data,
    loadPrevious,
    hasPrevious,
    // ... forward pagination values
  } = usePaginationFragment(
    graphql`
      fragment FriendsListComponent_user on User {
        name
        friends(after: $after, before: $before, first: $first, last: $last)
          @connection(key: "FriendsListComponent_user_friends_connection") {
          edges {
            node {
              name
              age
            }
          }
        }
      }
    `,
    userRef,
  );

  return (
    <>
      <h1>Friends of {data.name}:</h1>
      <List items={data.friends?.edges.map(edge => edge.node)}>
        {node => {
          return (
            <div>
              {node.name} - {node.age}
            </div>
          );
        }}
      </List>

      {hasPrevious ? (
        <Button onClick={() => loadPrevious(10)}>
          Load more friends
        </Button>
      ) : null}

      {/* Forward pagination controls can go simultaneously here */}
    </>
  );
}
```

### Streaming pagination

Combine `usePaginationFragment` with Relay's Incremental Data Delivery to fetch a connection and receive each item as it becomes ready. Use the `@stream_connection` directive in place of `@connection`.

```js
import type {FriendsListComponent_user$key} from 'FriendsList_user.graphql';

const React = require('React');

const {graphql, usePaginationFragment} = require('react-relay');

type Props = {
  user: FriendsListComponent_user$key,
};

function FriendsListComponent(props: Props) {
  // ...

  const {
    data,
    loadNext,
    hasNext,
  } = usePaginationFragment(
    graphql`
      fragment FriendsListComponent_user on User
      @refetchable(queryName: "FriendsListPaginationQuery") {
        name
        friends(first: $count, after: $cursor)
        @stream_connection(key: "FriendsList_user_friends", initial_count: 2,) {
          edges {
            node {
              name
              age
            }
          }
        }
      }
    `,
    props.user,
  );

  return (...);
}

module.exports = FriendsListComponent;
```

- `@stream_connection` accepts the same arguments as `@connection`, plus optional parameters that control streaming.
- `initial_count: Int` — optional, defaults to zero (docs). The SDL at both tags (`relay-extensions.graphql`) declares `initial_count: Int!`, so pass it always. It sets how many items the initial payload includes. Relay streams any later items. With zero, the list starts empty and all items stream. The number does not change how many items the connection returns in total.
- The connection updates as new items stream in from the server, and the component re-renders each time with the latest items.

### Multiple connections

To paginate over multiple connections in the same component, call `usePaginationFragment` multiple times. The docs recommend a single connection per component, which keeps the components easier to follow.

### Connection identity

The `@connection` directive requires a `key` argument, a unique string. The `filters` argument of `@connection` sets the exact set of filter values that are part of the identity of the connection.

### Suspense behavior

- The component suspends if fragment data is missing and a parent query is fetching it.
- `loadNext` and `loadPrevious` can cause the component, or new child components, to suspend. Wrap the component in a `Suspense` boundary from above, and use a transition to show a pending or loading state. Use `startTransition` to schedule the `loadNext` update:

```js
function StoryCommentsSection({story}) {
  const {
    data,
    hasNext,
    loadNext,
    isLoadingNext,
  } = usePaginationFragment(StoryCommentsSectionFragment, story);
  return (
    <>
      {data.comments.edges.map(commentEdge => {
        return (
          <Suspense fallback={<Glimmer />}>
            <Comment comment={commentEdge.node} />
          </Suspense>
        );
      })}
      {hasNext && (
        <LoadMoreCommentsButton
          onClick={() => {
            startTransition(() => {
              loadNext(3)
            });
          }}
          disabled={isLoadingNext}
        />
      )}
      {isLoadingNext && <SmallSpinner />}
    </>
  );
}
```

---

## usePrefetchableForwardPaginationFragment

Experimental API, subject to change. It is similar to `usePaginationFragment`. It prefetches `bufferSize` items to fill a buffer without displaying them. When `loadNext` runs, it takes items from the buffer first. It supports forward pagination only: `loadNext`, `hasNext` and `isLoadingNext`.

```js
import type {FriendsList_user$key} from 'FriendsList_user.graphql';

const React = require('React');

const {graphql, usePrefetchableForwardPaginationFragment} = require('react-relay');

type Props = {
  user: FriendsList_user$key,
};

function FriendsList(props: Props) {
  const {
    data,
    edges, // NOTE: It is required to use `edges` to access the items
    loadNext,
    hasNext,
    isLoadingNext,
    refetch, // For refetching connection
  } = usePrefetchableForwardPaginationFragment(
    graphql`
      fragment FriendsListComponent_user on User
      @refetchable(queryName: "FriendsListPaginationQuery") {
        name
        friends(first: $count, after: $cursor)
        @connection(key: "FriendsList_user_friends", prefetchable_pagination: true) {
          edges {
            node {
              name
              age
            }
          }
        }
      }
    `,
    props.user,
  );

  return (
    <>
      <h1>Friends of {data.name}:</h1>

      <List items={edges.map(edge => edge.node)}>
        {node => {
          return (
            <div>
              {node.name} - {node.age}
            </div>
          );
        }}
      </List>
      <Button onClick={() => loadNext(10)}>Load more friends</Button>
    </>
  );
}

module.exports = FriendsList;
```

- The fragment must have an `@connection` directive on a connection field with `prefetchable_pagination` set to `true`. Without it, the hook throws an error.
- The fragment must have a `@refetchable` directive. Without it, the hook throws an error.
- Render from the returned `edges`. The list excludes the buffer. Do not use the connection edges from `data` to render, or the hook does not work.
- `isLoadingNext` stays `false` while the hook prefetches to fill the buffer and the code has not asked for more items.

| Argument | Behavior |
|---|---|
| `bufferSize` | Size of the buffer. The component always tries to prefetch to fill the buffer. |
| `initialSize` | Optional. Initial number of items to display. Without it, the component shows all available items on the initial render or on refetch. |
| `prefetchingLoadMoreOptions` | Optional. Fetching arguments for the automatic prefetch. `options.onComplete` is called when the request completes. If an error occurs, it receives an `Error` object as the first parameter. |
| `minimumFetchSize` | Optional. Minimum number of items to fetch in any request. |

- `hasNext` is `true` if more items exist to query for, or more items exist in the buffer.
- `loadNext(count, options)` shows `count` more items from the buffer, or fetches them. The component first tries to fill the request from the buffer. If the buffer has too few items, it sends a request, and `isLoadingNext` is true while the request is in flight. `loadNext` returns `void`.
- The component fetches more items to fill the buffer in `useEffect`.
- `loadNext` does not suspend the component.

---

## useMutation

Executes a mutation in a React component.

```js
import type {FeedbackLikeMutation} from 'FeedbackLikeMutation.graphql';
const React = require('React');

const {graphql, useMutation} = require('react-relay');

function LikeButton() {
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

  if (isInFlight) {
    return <Spinner />;
  }

  return (
    <button
      onClick={() => {
        commit({
          variables: {
            input: {
              id: '123',
              text: 'text',
            },
          },
          onCompleted(data) {
            console.log(data);
          },
        });
      }}
    />
  );
}
```

### Arguments

- `mutation` — GraphQL mutation specified with a `graphql` template literal.
- `commitMutationFn` — optional. A function with the signature of `commitMutation`, called in its stead. Defaults to `commitMutation`.

### Return value

A tuple:

- `[0] commit` — executes the mutation. Its config is almost the same as the `commitMutation` config.
- `[1] isInFlight` — `true` if any mutation that `commit` triggered is still in flight. Multiple mutations can be in flight at once.

### Commit options

- `variables` — variables for the mutation. If the mutation defines an `$input` variable, the object has an `input` key. Its shape matches the data that the mutation expects in the GraphQL schema.
- `onCompleted` — called when the request completes and the in-memory Relay store is updated with the `updater` function. The value passed to `onCompleted` is the mutation fragment as read from the store after updaters and declarative mutation directives apply. Data from within unmasked fragments is not read, and records that `@deleteRecord` deleted can be `null`.
- `onError` — called if Relay encounters an error during the request.
- `onUnsubscribe` — called when the returned `Disposable` is disposed.
- `optimisticResponse` — object that updates the local in-memory store at once, before the mutation request completes. Its type matches the raw response type of the mutation, so decorate the mutation with `@raw_response_type`. Relay uses it to update the fields of the relevant records before `optimisticUpdater` runs. If the request errors, Relay rolls back the optimistic update.
- `optimisticUpdater` — function that updates the local in-memory store at once, before the request completes. It receives a `store`, a proxy of the in-memory Relay Store. If the request errors, Relay rolls back the update. Prefer `optimisticResponse` unless you need updates more complicated than field updates, for example deleting records or adding items to collections. Often the same function serves as `updater`.
- `updater` — function that updates the local store from the real server response. Without it, Relay updates the fields of the records in the mutation response. Pass an `updater` for more complicated updates, for example deleting records or adding items to collections. When the server response arrives, Relay first reverts the changes of `optimisticUpdater` and `optimisticResponse`, then runs `updater`.
- `uploadables` — map of uploadable items, one key per item. Each value is a `File` or `Blob`.
- There is no environment argument. `useMutation` uses the environment that `RelayEnvironmentProvider` provides.

`commit` returns a `disposable` object. `disposable.dispose()` reverts the optimistic update. Relay then does not update the store or call any success or error callback, but the network request is not guaranteed to be cancelled. If `dispose` runs after the mutation succeeded, it does not roll back the update in the Relay store.

### Pitfalls

- Optimistic responses contain many pitfalls. An optimistic response can include the content of fragment spreads. If a developer selects more fields in components whose fragments the optimistic response spreads, those components can have inconsistent or partial data during an optimistic update. The type of the optimistic response includes all nested fragments, so it can be very large. `@raw_response_type` can degrade the performance of the Relay compiler.
- On v20 the hook skips `isInFlight` state updates after the component unmounts. On v21 it does not guard them (`useMutation.js`, `isMountedRef` removed).

---

## useSubscription

Subscribes and unsubscribes to a subscription.

```js
import {graphql, useSubscription} from 'react-relay';
import {useMemo} from 'react';

const subscription = graphql`
  subscription UserDataSubscription($input: InputData!) {
    # ...
  }
`;

function UserComponent({ id }) {
  // IMPORTANT: your config should be memoized.
  // Otherwise, useSubscription will re-render too frequently.
  const config = useMemo(() => ({
    variables: {id},
    subscription,
  }), [id, subscription]);

  useSubscription(config);

  return (/* ... */);
}
```

### Arguments

- `config` — a memoized config of type `GraphQLSubscriptionConfig`, passed to `requestSubscription`.
- `requestSubscriptionFn` — optional. A function with the signature of `requestSubscription`, called in its stead. Defaults to `requestSubscription`.

### Behavior

`useSubscription` is a thin wrapper around the `requestSubscription` API. It:

- subscribes when the component mounts with the given config;
- unsubscribes when the component unmounts;
- unsubscribes and resubscribes with new values if the environment, the config or `requestSubscriptionFn` changes.

For more complicated cases, such as imperatively requesting a subscription, use the `requestSubscription` API directly.

Spreading the fragments of the components that show the data into the subscription payload is generally preferable to refetching the data in response to subscription events. The updated data arrives in a single round trip.

Configure the network layer to handle subscriptions.

---

## useClientQuery

Renders queries that read only client fields. The Relay Compiler supports client-side extensions of the schema, which define local fields and types.

```graphql
# example client extension of the `Query` type
extend type Query {
  client_field: String
}
```

Relay does not send these client-only fields to the server. Update them with the APIs for local updates, for example `commitPayload`.

```js
const React = require('React');

const {graphql, useClientQuery} = require('react-relay');

function ClientQueryComponent() {
  const data = useClientQuery(
    graphql`
      query ClientQueryComponentQuery {
        client_field
      }
    `,
    {}, // variables
  );

  return (
    <div>{data.client_field}</div>
  );
}
```

### Arguments

- `query` — GraphQL query specified with a `graphql` template literal.
- `variables` — object with the variable values for the query. They match the GraphQL variables declared in the query.

### Return value

- `data` — object with the data read from the Relay store. The object matches the shape of the query.

### Behavior

The hook works as `useLazyLoadQuery` with `fetchPolicy: store-only`. It sends no network request.

---

## useRelayEnvironment

Accesses a Relay environment that a `RelayEnvironmentProvider` set.

```js
const React = require('React');

const {useRelayEnvironment} = require('react-relay');

function MyComponent() {
  const environment = useRelayEnvironment();

  const handler = useCallback(() => {
    // For example, can be used to pass the environment to functions
    // that require a Relay environment.
    commitMutation(environment, ...);
  }, [environment])

  return (...);
}

module.exports = MyComponent;
```

---

## Fetch policy by API

| API | Accepted `fetchPolicy` | Default |
|---|---|---|
| `useLazyLoadQuery` | `store-or-network`, `store-and-network`, `network-only`, `store-only` | `store-or-network` |
| `useClientQuery` | none; it works as `useLazyLoadQuery` with `store-only` | `store-only` |
| `loadQuery`, `useQueryLoader` loader | `store-or-network`, `store-and-network`, `network-only`. The docs API page lists these 3. The source at v20.1.1 and v21.0.1 (`loadQuery.js`) also handles `store-only`. | `store-or-network` |
| `refetch` of `useRefetchableFragment` and `usePaginationFragment` | `fetchPolicy` option; see "Fetch Policies" in the Relay docs | none |
| `fetchQuery` | `network-only`, `store-or-network` | `network-only` |
