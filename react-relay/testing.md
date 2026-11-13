# Testing Relay

Reference for testing Relay components with the APIs from `relay-test-utils`. It covers the mock environment, `MockPayloadGenerator`, the `@relay_test_operation` directive, resolving operations, fragments, mutations, pagination, subscriptions and preloaded queries.

The content focuses on jest unit tests (individual components) and integration tests (a combination of components). Treat jest tests as one part of a bigger stability infrastructure with multiple layers of automated testing: flow, e2e, screenshot, "Redbox" and performance tests.

## Testing with Relay

Testing applications that use Relay can be hard, because of the additional data fetching layer that wraps the product code. Relay provides tools that simplify the tests for Relay components: imperative APIs that control the request/response flow, and an API for mock data generation.

There are two main Relay modules for your tests:

- `createMockEnvironment(options): RelayMockEnvironment`
- `MockPayloadGenerator` and the `@relay_test_operation` directive

`createMockEnvironment` creates an instance of `RelayMockEnvironment`, a Relay environment for tests. The instance implements the Relay Environment Interface and has an additional Mock layer. The methods of this layer resolve, reject and control the flow of operations (queries, mutations, subscriptions).

`MockPayloadGenerator` improves the creation and maintenance of mock data for tested components. Without it, most of the test code is test preparation: a large, manually created mock object with dummy data or a copy of a sample server response. With `MockPayloadGenerator` and `@relay_test_operation`, the focus of the developer moves from the preparation of the test to the actual testing.

[React Testing Library](https://testing-library.com/react) is a set of helpers that let you test React components without relying on their implementation details. A test runner like Jest can [mock modules](https://reactjs.org/docs/testing-recipes.html#mocking-modules) to render a component without its children.

## `RelayMockEnvironment` API overview

`RelayMockEnvironment` is a special version of the Relay Environment with additional API methods. They control the operation flow: resolving and rejecting operations, providing incremental payloads for subscriptions, and working with the cache.

Methods for finding operations that were executed on the environment:

| Method | Purpose |
|---|---|
| `getAllOperations()` | Get all operations executed during the test by the current time. |
| `findOperation(findFn => boolean)` | Find a particular operation in the list of all executed operations. Throws if the operation is not available. Useful when multiple operations execute at the same time. |
| `getMostRecentOperation()` | Return the most recent operation. Throws if no operation was executed before the call. |

Methods for resolving or rejecting operations:

| Method | Purpose |
|---|---|
| `nextValue(request \| operation, data)` | Provide a payload for the operation, but do not complete the request. Useful for incremental updates and subscriptions. |
| `complete(request \| operation)` | Complete the operation. No more payloads are expected for it. |
| `resolve(request \| operation, data)` | Resolve the request with the provided GraphQL response. Equal to `nextValue(...)` and `complete(...)`. |
| `reject(request \| operation, error)` | Reject the request with a particular error. |
| `resolveMostRecentOperation(operation => data)` | Resolve the most recent operation (`resolve` and `getMostRecentOperation` together). |
| `rejectMostRecentOperation(operation => error)` | Reject the most recent operation (`reject` and `getMostRecentOperation` together). |
| `queueOperationResolver(operation => data \| error)` | Add an OperationResolver function to the queue. Relay uses the resolver to resolve or reject operations as they appear. |
| `queuePendingOperation(query, variables)` | Record a pending operation, so that the `usePreloadedQuery` hook does not suspend. |

Additional utility methods:

| Method | Purpose |
|---|---|
| `isLoading(request \| operation)` | Return `true` if the operation is not completed yet. |
| `cachePayload(request \| operation, variables, payload)` | Add a payload to the QueryResponse cache. |
| `clearCache()` | Clear the QueryResponse cache. |

For `usePreloadedQuery` to not suspend, call these functions:

- `queueOperationResolver(resolver)`
- `queuePendingOperation(query, variables)`
- `preloadQuery(mockEnvironment, query, variables)` with the same `query` and `variables` as in `queuePendingOperation`. `preloadQuery` must be called after `queuePendingOperation`.

The `preloadQuery` name comes from the v21 guide. The `loadQuery` function of `react-relay` is the call that the hook-based API uses.

## Mock Payload Generator and the `@relay_test_operation` directive

`MockPayloadGenerator` generates dummy data for the selection in your operation. Mock Resolvers adjust the generated data. A Mock Resolver set is an object whose keys are names of GraphQL types (`ID`, `String`, `User`, `Comment`, etc) and whose values are functions that return the default data for the type.

A simple Mock Resolver:

```js
{
  ID() {
    // Return mock value for a scalar filed with type ID
    return 'my-id';
  },
  String() {
    // Every scalar field with type String will have this default value
    return "Lorem Ipsum"
  }
}
```

Resolvers for Object types:

```js
{
  // This will be the default values for User object in the query response
  User() {
    return {
      id: 4,
      name: "Mark",
      profile_picture: {
        uri: "http://my-image...",
      },
    };
  },
}
```

### Mock Resolver Context

The first argument of a Mock Resolver is an object that contains the Mock Resolver Context. A resolver can return dynamic values based on the context: the name or alias of the field, a path in the selection, arguments, or the parent type.

```js
{
  String(context) {
    if (context.name === 'zip') {
      return '94025';
    }
    if (context.path != null && context.path.join('.') === 'node.actor.name') {
      return 'Current Actor Name';
    }
    if (context.parentType === 'Image' && context.name === 'uri') {
       return 'http://my-image.url';
    }
  }
}
```

### ID generation

The second argument of a Mock Resolver is a function that generates a sequence of integers. Use it to generate unique ids in tests.

```js
{
  // will generate strings "my-id-1", "my-id-2", etc.
  ID(_, generateId) {
     return `my-id-${generateId()}`;
  },
}
```

### Float, Integer, Boolean, etc.

For production queries, Relay has no full type information for scalar fields like Boolean, Integer and Float. In Mock Resolvers they map to String. Use `context` to adjust return values based on the field name, alias, etc.

### `@relay_test_operation`

Most of the GraphQL type information for a field in the selection is not available at Relay runtime. By default, Relay cannot get type information for a scalar field in the selection or for an interface type of the object.

An operation with the `@relay_test_operation` directive has additional metadata with GraphQL type information for the fields in the selection of the operation. This improves the quality of the generated data. You can then define Mock Resolvers for Scalar (other than ID and String) and Abstract types:

```javascript
{
  Float() {
    return 123.456;
  },
  Boolean(context) {
    if (context.name === 'can_edit') {
      return true;
    }
    return false;
  },
  Node() {
    return {
      __typename: 'User',
      id: 'my-user-id',
    };
  }
}
```

## Examples

### Relay component test

`createMockEnvironment` and `MockPayloadGenerator` allow concise tests for components that use Relay hooks. Import both from `relay-test-utils`.

Relay can trigger 3 states for a component: Loading, Error and Data Loaded. Wrap the resolution in `act` so that components are fully updated to their final state. Simulate an error with `rejectMostRecentOperation`.

```javascript
// Say you have a component with the useLazyLoadQuery or a QueryRenderer
const MyAwesomeViewRoot = require('MyAwesomeViewRoot');
const {
  createMockEnvironment,
  MockPayloadGenerator,
} = require('relay-test-utils');
const {act, render} = require('@testing-library/react');

// Relay may trigger 3 different states
// for this component: Loading, Error, Data Loaded
// Here is examples of tests for those states.
test('Loading State', async () => {
  const environment = createMockEnvironment();
  const renderer = render(
    <MyAwesomeViewRoot environment={environment} />,
  );

  // Here we just verify that the spinner is rendered
  expect(await renderer.findByTestId('spinner')).toBeDefined();
});

test('Data Render', async () => {
  const environment = createMockEnvironment();
  const renderer = render(
    <MyAwesomeViewRoot environment={environment} />,
  );

  // Wrapping in act will ensure that components
  // are fully updated to their final state.
  act(() => {
    environment.mock.resolveMostRecentOperation(operation =>
      MockPayloadGenerator.generate(operation),
    );
  });

  // At this point operation will be resolved
  // and the data for a query will be available in the store
  expect(await renderer.findByTestId('myButton')).toBeDefined();
});

test('Error State', async () => {
  const environment = createMockEnvironment();
  const renderer = render(
    <MyAwesomeViewRoot environment={environment} />,
  );

  // Wrapping in act will ensure that components
  // are fully updated to their final state.
  act(() => {
    // Error can be simulated with `rejectMostRecentOperation`
    environment.mock.rejectMostRecentOperation(new Error('Uh-oh'));
  });

  expect(await renderer.findByTestId('errorMessage')).toBeDefined();
});
```

#### Component tests with deferred fragments

When a query has fragments with `@defer`, use `MockPayloadGenerator.generateWithDefer` with the option `generateDeferredPayload` to generate the deferred data as well:

```javascript
// Say you have a component with useFragment
const ChildComponent = (props: {user: ChildComponentFragment_user$key}) => {
  const data = useFragment(graphql`
  fragment ChildComponentFragment_user on User {
    name
  }
  `, props.user);
  return <View>{data?.name}</View>;
};

// Say you have a parent component that fetches data with useLazyLoadQuery and `@defer`s the data for the ChildComponent.
const ParentComponent = () => {
  const data = useLazyLoadQuery(graphql`
  query ParentComponentQuery {
    user {
      id
      ...ChildComponentFragment_user @defer
    }
  }
  `, {});
  return (
    <View>
      {id}
      <Suspense fallback={null}>
        {data?.user && <ChildComponent user={data.user} />}
      </Suspense>
    </View>
  );
};

const {
  createMockEnvironment,
  MockPayloadGenerator,
} = require('relay-test-utils');
const {act, render} = require('@testing-library/react');

test('Data Render with @defer', () => {
  const environment = createMockEnvironment();
  const renderer = render(
    <RelayEnvironmentProvider environment={environment}>
      <ParentComponent />,
    </RelayEnvironmentProvider>
  );

  // Wrapping in ReactTestRenderer.act will ensure that components
  // are fully updated to their final state.
  act(() => {
    const operation = environment.mock.getMostRecentOperation();
    const mockData = MockPayloadGenerator.generateWithDefer(operation, null, {generateDeferredPayload: true});
    environment.mock.resolve(mockData);

    // You may need this to make sure all payloads are retrieved
    jest.runAllTimers();
  });

  // At this point operation will be resolved
  // and the data for a query will be available in the store
  expect(renderer.container.textContent).toEqual(['id', 'name']);
});
```

Pass the operation as the first argument of `environment.mock.resolve`. The v21 guide example calls `environment.mock.resolve(mockData)` with one argument, which does not match the source signature.

### Fragment component tests

`resolveMostRecentOperation` generates data for all child fragment containers (pagination, refetch). A root component can have many child fragment components. To exercise one component that uses `useFragment`, wrap it with a `useLazyLoadQuery` component that renders a Query that spreads the fragments from your fragment component:

```javascript
test('Fragment', () => {
  const environment = createMockEnvironment();
  const TestRenderer = () => {
    const data = useLazyLoadQuery(
      graphql`
        query TestQuery @relay_test_operation {
          myData: node(id: "test-id") {
            # Spread the fragment you want to test here
            ...MyFragment
          }
        }
      `,
      {},
    );
    return <MyFragmentComponent myData={data.myData} />
  };

  const renderer = render(
    <RelayEnvironmentProvider environment={environment}>
      <Suspense fallback="Loading...">
        <TestRenderer />
      </Suspense>
    </RelayEnvironmentProvider>
  );

  // Wrapping in act will ensure that components
  // are fully updated to their final state.
  act(() => {
    environment.mock.resolveMostRecentOperation(operation =>
      MockPayloadGenerator.generate(operation),
    );
  });

  expect(renderer).toMatchSnapshot();
});
```

### Pagination component test

Tests for pagination components (for example with `usePaginationFragment`) are like fragment component tests. You can also assert the behavior of the component when it paginates (load more, refetch).

```js
// Pagination Example
test('`Pagination` Container', async () => {
  const environment = createMockEnvironment();
  const TestRenderer = () => {
    const data = useLazyLoadQuery(
      graphql`
        query TestQuery @relay_test_operation {
          myConnection: node(id: "test-id") {
            connection {
              # Spread the pagination fragment you want to test here
              ...MyConnectionFragment
            }
          }
        }
      `,
      {},
    );
    return <MyPaginationContainer connection={data.myConnection.connection} />
  };

  const renderer = render(
    <RelayEnvironmentProvider environment={environment}>
      <Suspense fallback="Loading...">
        <TestRenderer />
      </Suspense>
    </RelayEnvironmentProvider>
  );

  // Wrapping in act will ensure that components
  // are fully updated to their final state.
  act(() => {
    environment.mock.resolveMostRecentOperation(operation =>
      MockPayloadGenerator.generate(operation, {
        ID(_, generateId) {
          // Why we're doing this?
          // To make sure that we will generate a different set of ID
          // for elements on first page and the second page.
          return `first-page-id-${generateId()}`;
        },
        PageInfo() {
          return {
            has_next_page: true,
          };
        },
      }),
    );
  });

  // Let's find a `loadMore` button and click on it to initiate pagination request, for example
  const loadMore = await renderer.findByTestId('loadMore');
  expect(loadMore.props.disabled).toBe(false);
  loadMore.props.onClick();

  // Wrapping in act will ensure that components
  // are fully updated to their final state.
  act(() => {
    environment.mock.resolveMostRecentOperation(operation =>
      MockPayloadGenerator.generate(operation, {
        ID(_, generateId) {
          // See, the second page IDs will be different
          return `second-page-id-${generateId()}`;
        },
        PageInfo() {
          return {
            // And the button should be disabled, now. Probably.
            has_next_page: false,
          };
        },
      }),
    );
  });

  expect(loadMore.props.disabled).toBe(true);
});
```

### Refetch component

Wrap the component with a query in the same way:

```js
test('Refetch Container', async () => {
  const environment = createMockEnvironment();
  const TestRenderer = () => {
    const data = useLazyLoadQuery(
      graphql`
        query TestQuery @relay_test_operation {
          myData: node(id: "test-id") {
            # Spread the pagination fragment you want to test here
            ...MyRefetchableFragment
          }
        }
      `,
      {},
    );
    return <MyRefetchContainer data={data.myData} />
  };

  const renderer = render(
    <RelayEnvironmentProvider environment={environment}>
      <Suspense fallback="Loading...">
        <TestRenderer />
      </Suspense>
    </RelayEnvironmentProvider>
  );

  act(() => {
    environment.mock.resolveMostRecentOperation(operation =>
      MockPayloadGenerator.generate(operation),
    );
  });

  // Assuming we have refetch button in the Container
  const refetchButton = await renderer.findByTestId('refetch');

  // This should trigger the `refetch`
  refetchButton.props.onClick();

  act(() => {
    environment.mock.resolveMostRecentOperation(operation =>
      MockPayloadGenerator.generate(operation, {
        // We can customize mock resolvers, to change the output of the refetch query
      }),
    );
  });

  expect(renderer).toMatchSnapshot();
});
```

### Mutations

Mutations are operations. Test a specific mutation independently (unit test), or in combination with the view that calls it. The `useMutation` API is an improvement over calling `commitMutation` directly.

```js
// Say, you have a mutation function
function sendMutation(environment, onCompleted, onError, variables)
  commitMutation(environment, {
    mutation: graphql`...`,
    onCompleted,
    onError,
    variables,
  });
}

// Example test may be written like so
test('it should send mutation', () => {
  const environment = createMockEnvironment();
  const onCompleted = jest.fn();
  sendMutation(environment, onCompleted, jest.fn(), {});
  const operation = environment.mock.getMostRecentOperation();

  act(() => {
    environment.mock.resolve(
      operation,
      MockPayloadGenerator.generate(operation)
    );
  });

  expect(onCompleted).toBeCalled();
});
```

### Subscriptions

The `useSubscription` API is an improvement over calling `requestSubscription` directly. Test subscriptions in the same way as mutations.

```js
// Example subscribe function
function subscribe(environment, onNext, onError, variables)
  requestSubscription(environment, {
    subscription: graphql`...`,
    onNext,
    onError,
    variables,
  });
}

// Example test may be written like so
test('it should subscribe', () => {
  const environment = createMockEnvironment();
  const onNext = jest.fn();
  subscribe(environment, onNext, jest.fn(), {});
  const operation = environment.mock.getMostRecentOperation();

  act(() => {
    environment.mock.nextValue(
      operation,
      MockPayloadGenerator.generate(operation)
    );
  });

  expect(onNext).toBeCalled();
});
```

### Example with `queueOperationResolver`

`queueOperationResolver` defines responses for operations that execute on the environment:

```javascript
// Say you have a component with the QueryRenderer
const MyAwesomeViewRoot = require('MyAwesomeViewRoot');
const {
  createMockEnvironment,
  MockPayloadGenerator,
} = require('relay-test-utils');

test('Data Render', async () => {
  const environment = createMockEnvironment();
  environment.mock.queueOperationResolver(operation =>
    MockPayloadGenerator.generate(operation),
  );

  const renderer = render(
    <MyAwesomeViewRoot environment={environment} />,
  );

  // At this point operation will be resolved
  // and the data for a query will be available in the store
  expect(await renderer.findByTestId('myButton')).toBeDefined();
});

test('Error State', async () => {
  const environment = createMockEnvironment();
  environment.mock.queueOperationResolver(() =>
    new Error('Uh-oh'),
  );
  const renderer = render(
    <MyAwesomeViewRoot environment={environment} />,
  );

  expect(await renderer.findByTestId('myButton')).toBeDefined();
});
```

### With Relay Hooks

The examples in this guide work for testing components with Relay Hooks, Containers or Renderers. For tests that involve the `usePreloadedQuery` hook, see "Testing preloaded queries" below.

### `toMatchSnapshot(...)`

The examples here use `toMatchSnapshot()` assertions to stay concise. `toMatchSnapshot()` is not the recommended way to test your components.

## Testing preloaded queries

Components that use preloaded queries (`useQueryLoader` and `usePreloadedQuery` hooks) need a slightly different and more convoluted test setup. Two steps are required **before rendering the component**:

1. Configure the query resolver to generate the response with `environment.mock.queueOperationResolver`.
2. Record a pending queue invocation with `environment.mock.queuePendingOperation`.

Symptoms that something is wrong:

1. The test does not do what you expect.
2. The query seems to block and does not execute. For example, the `Suspense` does not switch from the "waiting" state to the "data loaded" state.
3. With `console.log` before and after `usePreloadedQuery`, only the "before" call is hit.

```javascript
const {RelayEnvironmentProvider} = require('react-relay');
const {MockPayloadGenerator, createMockEnvironment} = require('relay-test-utils');
const {act, render} = require('@testing-library/react');
test("...", () => {
  // arrange
  const environment = createMockEnvironment();
  environment.mock.queueOperationResolver(operation => {
      return MockPayloadGenerator.generate(operation, {
        CurrencyAmount() {
          return {
            formatted_amount: "1234$",
          };
        },
      });
    });
  const query = YourComponentGraphQLQueryGoesHere; // can be the same, or just identical
  const variables = {
    // ACTUAL variables for the invocation goes here
  };
  environment.mock.queuePendingOperation(YourComponentGraphQLQuery, variables);

 // act
  const {getByTestId, ..otherStuffYouMightNeed} = render(
    <RelayEnvironmentProvider environment={environment}>
        <YourComponent data-testid="1234" {...componentPropsIfAny}/>
    </RelayEnvironmentProvider>
  );
  // trigger the loading - click a button, emit an event, etc. or ...
  act(() => jest.runAllImmediates()); // ... if loadQuery is in the useEffect()
  // assert
  // your assertions go here
});
```

### Configure the query resolver to generate the response

Call `environment.mock.queueOperationResolver(operation)`. The resolver returns a mocked GraphQL result as a `MockResolvers` object. The keys of this object are the GraphQL types that you want to mock (see the Mock Payload Generator section above).

```js
return MockPayloadGenerator.generate(operation, {
  CurrencyAmount() { // <-- the GraphQL type
    return {
      formatted_amount: "response_value" <-- CurrencyAmount fields, selected in the query
    };
  }
});
```

To get the name of the GraphQL type and the fields to return, call `console.log(JSON.stringify(operation, null, 2))`. Look for the `concreteType` that corresponds to what you want to mock. The sibling `selections` array describes the fields that the query selects from that object.

A resolver can return different data for different query variables with the Mock Resolver Context. The query variables are available on `context.args`, but only for the *innermost function call*.

```javascript
CurrencyAmount(context) {
  console.log(JSON.stringify(context, null, 2)); // <--
  return { formatted_amount: mockResponse }
}
// <-- logs { ...snip..., "name": "subtotal_price_for_offers", args: { offer_ids: [...] } }
```

### Record a pending queue invocation

Call `environment.mock.queuePendingOperation(query, variables)`.

- `query` must match the query that the component issues. Export the query from the component module and use it in the test. An identical (but not the same) query works as well.
- `variables` must match the variables that the test invocation uses.
  - Arrays are compared by values (not by reference). The order of elements matters.
  - Nested objects are compared deeply. The order of keys is not relevant.

### Troubleshooting preloaded query tests

- Use `console.log` before and after `useQueryLoader`, `usePreloadedQuery` and `loadQuery` in the component, and in the `queueOperationResolver` callback in the test.
- If `loadQuery` is not called, issue the triggering event. Depending on the component, it is a user action (button click, key press), a javascript event, or a delayed execution with `useEffect`.
  - For the `useEffect` case, call `act(() => jest.runAllImmediates())` **after** rendering the component.
- If "before" `usePreloadedQuery` is hit but "after" is not, the query suspends. The cause is one of these:
  - A different query is used. The query resolver is not called, and `currentOperation` is `null`.
  - The query variables do not match. The query resolver is not called, and `currentOperation` is `null`. Inspect the `variables`, and make sure arrays are in the same order.
- If the data returned from the query is not what you expect, make sure you generate the right GraphQL type. Values such as `<mock-value-for-field-"formatted_amount">` show that you mock the wrong type.
- The component and the test must use the same environment. No `RelayEnvironmentProvider` with another environment may be nested in the test React tree.
- The examples use `testing-library-react`. They also work with `react-test-renderer`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `getMostRecentOperation` throws | No operation was executed before the call | Render first, then call `getMostRecentOperation()`. |
| `usePreloadedQuery` never completes | Missing `queuePendingOperation`, or variable mismatch | Call `queuePendingOperation(query, vars)` with the same variables as the component. |
| `queueOperationResolver` not firing | Registered after the operation was issued | Register the resolver before you render the component. |
| Scalar resolvers ignored | Missing `@relay_test_operation` directive | Add `@relay_test_operation` to the query used in tests. |
| Components not fully updated | Resolution not wrapped in `act` | Wrap the resolve/reject call in `act(() => { ... })`. |
| Duplicate IDs across pagination pages | Same ID pattern for both pages | Use a different ID prefix per page in the `ID` resolver. |
| `loadQuery` inside `useEffect` not fetching | Immediate never flushed | `act(() => jest.runAllImmediates())` after render. |
| Subscription only emits once | Used `resolve`, which completes the request | Use `nextValue` for each payload; `complete` when done. |
| Mock values look like `<mock-value-for-field-"x">` | Mocked the wrong type | Log the operation JSON and mock the type that owns the field. |
| Deferred data never renders | Used `generate` for a query with `@defer` | Use `generateWithDefer` with `generateDeferredPayload: true`. |
