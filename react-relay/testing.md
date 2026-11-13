# Testing Relay

Reference for testing Relay (hooks-only) components with Jest and React Testing Library using `relay-test-utils`. Covers mock environments, `MockPayloadGenerator`, operation resolution, fragments, mutations, pagination, subscriptions, and preloaded queries.

## Install

```bash
npm install --save-dev relay-test-utils @testing-library/react @testing-library/jest-dom jest
```

`relay-test-utils` ships with the `relay` package family and works with any React Relay version that supports hooks.

## Core APIs

The main exports from `relay-test-utils` (the package also exports `MockEnvironment`, `unwrapContainer` and `testResolver`):

- `createMockEnvironment()` — returns a `RelayMockEnvironment` (an `Environment` plus a `.mock` controller).
- `MockPayloadGenerator` — synthesizes payloads from an operation descriptor.

The `.mock` controller on the environment exposes:

| Method | Purpose |
|---|---|
| `getAllOperations()` | Every pending operation in order. |
| `getMostRecentOperation()` | Latest pending operation (throws if none). |
| `findOperation(fn)` | First operation matching predicate (throws if none). |
| `resolveMostRecentOperation(op => payload)` | Resolve latest with generated data. |
| `rejectMostRecentOperation(error \| op => error)` | Fail latest with error. |
| `nextValue(request, data)` | Emit payload without completing (subscriptions, `@stream`). |
| `complete(request)` | Complete a request previously fed with `nextValue`. |
| `resolve(request, data)` | `nextValue` + `complete`. |
| `reject(request, error)` | Fail a specific request. |
| `queueOperationResolver(resolver)` | Queue a resolver that resolves 1 later operation. |
| `queuePendingOperation(query, variables)` | Pre-seed an operation so `usePreloadedQuery` will not suspend indefinitely. |
| `isLoading(request, variables, cacheConfig?)` | `true` if pending. |
| `cachePayload(request, vars, payload)` | Seed the QueryResponse cache. |
| `clearCache()` | Reset cache. |

### Mock method rules

- `isLoading(request, variables, cacheConfig?)` takes the variables of the request. It returns `true` while a matching request is pending.
- `reject(request, error)` accepts an `Error` or a string. A string becomes `new Error(string)`.
- `nextValue(request, payload)` requires an object with a `data` key. Other values throw `MockEnvironment(): Expected payload to be an object with a `data` key.`
- `resolve(request, payload)` accepts one payload or an array of payloads. It emits each payload and then completes the request.
- `getMostRecentOperation()` throws when no operation is pending.
- `queueOperationResolver(resolver)` registers a one-shot resolver. Relay checks only the first resolver in the queue when an operation starts.
  - A resolver that returns a payload resolves the operation and leaves the queue.
  - A resolver that returns an `Error` rejects the operation and leaves the queue.
  - A resolver that returns `null` or `undefined` stays in the queue, and the operation stays pending.
  - A resolver applies only to an operation that is pending in the environment. Register one resolver for each operation you expect.

## `createMockEnvironment(config)`

The function accepts an optional `Partial<EnvironmentConfig>`. It spreads the config over its defaults. Pass `store`, `missingFieldHandlers`, `handlerProvider`, `getDataID`, `log` or `relayFieldLogger` to test the same wiring as production.

```ts
import { Store, RecordSource } from 'relay-runtime';

const environment = createMockEnvironment({
  store: new Store(new RecordSource(), { gcReleaseBufferSize: 0 }),
  missingFieldHandlers,
});
```

A `network` key replaces the mock network. `environment.mock.*` cannot resolve operations after that.

When `NODE_ENV` is `test`, the environment wraps `execute`, `executeMutation`, `executeSubscription`, `executeWithSource`, `applyUpdate`, `commitPayload`, `getStore`, `lookup`, `check`, `subscribe` and `retain` in `jest.fn`. The store methods `getSource`, `lookup`, `notify`, `publish`, `retain` and `subscribe` are wrapped too.

```ts
expect(environment.executeMutation).toHaveBeenCalledTimes(1);
environment.mockClear();
```

`environment.mockClear()` resets those mocks, the pending operations, the pending requests, the response cache and the record source.

## Enabling `@relay_test_operation`

Add the `@relay_test_operation` directive to test-only queries. It instructs the compiler to emit type metadata that `MockPayloadGenerator` needs for scalar and abstract-type mocking.

```ts
const testQuery = graphql`
  query UserTestQuery($id: ID!) @relay_test_operation {
    node(id: $id) {
      ... on User {
        ...UserCard_user
      }
    }
  }
`;
```

Without the directive, resolvers by type still work for concrete object types, and each scalar other than `ID` maps to `String`. Mock resolvers for `Int`, `Float`, `Boolean`, custom scalars and abstract types need `@relay_test_operation`.

## `createMockEnvironment()`

```ts
import { createMockEnvironment, MockPayloadGenerator } from 'relay-test-utils';
import { RelayEnvironmentProvider } from 'react-relay';

const environment = createMockEnvironment();

render(
  <RelayEnvironmentProvider environment={environment}>
    <MyComponent />
  </RelayEnvironmentProvider>
);
```

Create a fresh environment per test. Sharing state across tests causes cache bleed and stale operations.

```ts
let environment: ReturnType<typeof createMockEnvironment>;
beforeEach(() => {
  environment = createMockEnvironment();
});
```

## `MockPayloadGenerator.generate(operation, mockResolvers?)`

Generates a payload matching the operation's selection set. Second arg is a map from GraphQL type name to a resolver function.

```ts
environment.mock.resolveMostRecentOperation(operation =>
  MockPayloadGenerator.generate(operation)
);
```

With resolvers:

```ts
environment.mock.resolveMostRecentOperation(operation =>
  MockPayloadGenerator.generate(operation, {
    User: () => ({ id: 'u_1', name: 'Alice', email: 'alice@example.com' }),
    String: () => 'mock-string',
    ID: (_, gen) => `id-${gen()}`,
    Int: () => 42,
  })
);
```

Resolvers may return partial objects; unspecified fields are synthesized from the schema.

## Mocking by Type

Keys are GraphQL type names (`User`, `Post`, `CurrencyAmount`, `String`, `Int`, `ID`, `Float`, `Boolean`, and abstract types like `Node` if the query uses them abstractly).

```ts
MockPayloadGenerator.generate(operation, {
  User: () => ({ name: 'Alice', __typename: 'User' }),
  Organization: () => ({ name: 'Acme', membersCount: 12 }),
  PageInfo: () => ({ hasNextPage: false, endCursor: null }),
});
```

A resolver for a type applies wherever that type appears in the selection set.

## Default Mock Values

`MockPayloadGenerator` uses these values when no resolver matches.

| Type | Default |
|---|---|
| `ID` | `<TypeName-mock-id-N>` (`<mock-id-N>` when the parent type is unknown) |
| `String` and scalars without type metadata | `<mock-value-for-field-"fieldName">` |
| `Int` | `42` |
| `Float` | `4.2` |
| `Boolean` | `false` |
| Enum (needs `@relay_test_operation`) | First enum value |
| `__typename` of an abstract type | `__MockObject` |

Each call to `MockPayloadGenerator.generate` creates a new id counter that starts at 1. Two `generate` calls on one environment produce the same ids unless the resolvers add a prefix or an offset.

Fields inside `@client` extensions (client schema extensions) stay empty by default. Pass `mockClientData` to generate them:

```ts
MockPayloadGenerator.generate(operation, resolvers, { mockClientData: true });
```

## Path-Aware Mocks with `context`

Resolvers receive `(context, generateId)`. `context` has:

- `context.name` — field or alias name (e.g. `"name"`, `"firstEdge"`).
- `context.path` — array of field names from the root (e.g. `['node', 'actor', 'name']`).
- `context.parentType` — containing GraphQL type.
- `context.args` — the field's arguments at call site.

```ts
MockPayloadGenerator.generate(operation, {
  String: (context) => {
    if (context.path?.join('.') === 'node.actor.name') return 'Alice';
    if (context.name === 'url') return 'https://example.com';
    return `mock-${context.name}`;
  },
  ID: (_, generateId) => `id-${generateId()}`,
  Boolean: (context) => context.name === 'isActive',
});
```

`generateId()` returns an integer that increases within one `generate()` call. The count starts at 1 again for each `generate()` call.

## Deferred Fragments: `generateWithDefer`

`MockPayloadGenerator.generateWithDefer(operation, resolvers, options)` generates the initial payload and, on request, the payloads for `@defer` and `@stream` selections.

- With `{ generateDeferredPayload: true }`, it returns an array. The first element is the initial payload. Each next element has `path`, `label` and `data` for one deferred selection.
- Without the option, it returns the initial payload only.
- A `@defer(if: $var)` or `@stream(if: $var)` selection produces a deferred payload only when the variable is truthy.

```tsx
test('renders deferred fragment data', () => {
  const environment = createMockEnvironment();
  render(
    <RelayEnvironmentProvider environment={environment}>
      <Suspense fallback={null}>
        <ParentComponent />
      </Suspense>
    </RelayEnvironmentProvider>
  );

  act(() => {
    const operation = environment.mock.getMostRecentOperation();
    const payloads = MockPayloadGenerator.generateWithDefer(
      operation,
      { User: () => ({ id: 'u_1', name: 'Alice' }) },
      { generateDeferredPayload: true }
    );
    environment.mock.resolve(operation, payloads);
  });

  expect(screen.getByText('Alice')).toBeInTheDocument();
});
```

Pass the operation as the first argument of `environment.mock.resolve`. The v21 guide example calls `environment.mock.resolve(mockData)` with one argument, which does not match the source signature.

## Resolving Operations

### `resolveMostRecentOperation`

```ts
environment.mock.resolveMostRecentOperation(operation =>
  MockPayloadGenerator.generate(operation, {
    User: () => ({ name: 'Alice' }),
  })
);
```

Wrap in `act()` when the resolution triggers a React re-render:

```ts
import { act } from '@testing-library/react';

act(() => {
  environment.mock.resolveMostRecentOperation(op =>
    MockPayloadGenerator.generate(op)
  );
});
```

### `rejectMostRecentOperation`

```ts
environment.mock.rejectMostRecentOperation(new Error('Network failure'));
```

Or functional form:

```ts
environment.mock.rejectMostRecentOperation(op =>
  new Error(`Failed for ${op.fragment.node.name}`)
);
```

### `queueOperationResolver` (auto-resolve)

Register a resolver that fires for the next operation as it is sent. The resolver leaves the queue when it returns a payload or an error:

```ts
environment.mock.queueOperationResolver(operation =>
  MockPayloadGenerator.generate(operation, {
    User: () => ({ name: 'Alice' }),
  })
);
```

Unlike `resolveMostRecentOperation`, no manual resolve call is needed after render. Essential for preloaded queries (see below).

### `getAllOperations`

Inspect every pending operation — useful when multiple queries fire:

```ts
const ops = environment.mock.getAllOperations();
expect(ops).toHaveLength(2);
expect(ops[0].fragment.node.name).toBe('UserListQuery');
```

## Testing a Component with `useLazyLoadQuery`

```tsx
// UserCard.tsx
import { graphql, useLazyLoadQuery } from 'react-relay';

const query = graphql`
  query UserCardQuery($id: ID!) {
    user: node(id: $id) {
      ... on User {
        name
        email
      }
    }
  }
`;

export function UserCard({ id }: { id: string }) {
  const data = useLazyLoadQuery<UserCardQuery>(query, { id });
  return <div>{data.user?.name}</div>;
}
```

```tsx
// UserCard.test.tsx
import { Suspense } from 'react';
import { render, screen, act } from '@testing-library/react';
import { RelayEnvironmentProvider } from 'react-relay';
import { createMockEnvironment, MockPayloadGenerator } from 'relay-test-utils';
import { UserCard } from './UserCard';

test('renders user name', async () => {
  const environment = createMockEnvironment();

  render(
    <RelayEnvironmentProvider environment={environment}>
      <Suspense fallback={<div>Loading...</div>}>
        <UserCard id="u_1" />
      </Suspense>
    </RelayEnvironmentProvider>
  );

  expect(screen.getByText('Loading...')).toBeInTheDocument();

  act(() => {
    environment.mock.resolveMostRecentOperation(op =>
      MockPayloadGenerator.generate(op, {
        User: () => ({ name: 'Alice', email: 'alice@example.com' }),
      })
    );
  });

  expect(await screen.findByText('Alice')).toBeInTheDocument();
});
```

## Testing Fragments in Isolation

Fragments cannot render alone — wrap them in a test query that spreads the fragment.

```tsx
// UserAvatar.tsx
import { graphql, useFragment } from 'react-relay';

const fragment = graphql`
  fragment UserAvatar_user on User {
    name
    avatarUrl
  }
`;

export function UserAvatar({ userRef }: { userRef: UserAvatar_user$key }) {
  const user = useFragment(fragment, userRef);
  return <img alt={user.name} src={user.avatarUrl} />;
}
```

```tsx
// UserAvatar.test.tsx
import { graphql, useLazyLoadQuery } from 'react-relay';

function Harness() {
  const data = useLazyLoadQuery<UserAvatarTestQuery>(
    graphql`
      query UserAvatarTestQuery @relay_test_operation {
        user: node(id: "test") {
          ... on User {
            ...UserAvatar_user
          }
        }
      }
    `,
    {}
  );
  return data.user ? <UserAvatar userRef={data.user} /> : null;
}

test('renders avatar from fragment', () => {
  const environment = createMockEnvironment();
  render(
    <RelayEnvironmentProvider environment={environment}>
      <Suspense fallback={null}>
        <Harness />
      </Suspense>
    </RelayEnvironmentProvider>
  );

  act(() => {
    environment.mock.resolveMostRecentOperation(op =>
      MockPayloadGenerator.generate(op, {
        User: () => ({ name: 'Alice', avatarUrl: 'https://x/y.png' }),
      })
    );
  });

  expect(screen.getByAltText('Alice')).toHaveAttribute(
    'src',
    'https://x/y.png'
  );
});
```

## Testing Preloaded Queries

`usePreloadedQuery` requires both an auto-resolver and a pending operation, because the query reference is created before render.

```tsx
// UserProfile.tsx
import { graphql, usePreloadedQuery, PreloadedQuery } from 'react-relay';

export const userProfileQuery = graphql`
  query UserProfileQuery($id: ID!) {
    node(id: $id) {
      ... on User {
        name
      }
    }
  }
`;

export function UserProfile({
  queryRef,
}: {
  queryRef: PreloadedQuery<UserProfileQuery>;
}) {
  const data = usePreloadedQuery(userProfileQuery, queryRef);
  return <div>{data.node?.name}</div>;
}
```

```tsx
// UserProfile.test.tsx
import { loadQuery } from 'react-relay';
import { userProfileQuery, UserProfile } from './UserProfile';

test('renders preloaded profile', () => {
  const environment = createMockEnvironment();

  // 1. Register the auto-resolver BEFORE loadQuery.
  environment.mock.queueOperationResolver(op =>
    MockPayloadGenerator.generate(op, {
      User: () => ({ name: 'Alice' }),
    })
  );

  // 2. Mark the operation pending so usePreloadedQuery can find it.
  environment.mock.queuePendingOperation(userProfileQuery, { id: 'u_1' });

  // 3. Kick off the query.
  const queryRef = loadQuery(environment, userProfileQuery, { id: 'u_1' });

  render(
    <RelayEnvironmentProvider environment={environment}>
      <Suspense fallback={<div>Loading</div>}>
        <UserProfile queryRef={queryRef} />
      </Suspense>
    </RelayEnvironmentProvider>
  );

  expect(screen.getByText('Alice')).toBeInTheDocument();
});
```

Variables must match exactly. Arrays compare by order; objects compare deeply but ignore key order.

If `loadQuery` is inside a `useEffect`, flush it with:

```ts
import { act } from '@testing-library/react';
act(() => { jest.runAllImmediates(); });
```

### Debugging a Preloaded Query Test

- `usePreloadedQuery` suspends forever when the resolver never runs. The resolver runs only when the query and the variables match the pending operation. Check for a different query, different variables, or arrays in a different order.
- Log `JSON.stringify(operation, null, 2)` inside the resolver. Find the `concreteType` of the object to mock. The sibling `selections` array lists the fields that the query selects on it.
- Mock the type that the field returns. A wrong type produces values such as `<mock-value-for-field-"formatted_amount">`.
- `context.args` holds the field arguments only for the innermost field call that selects the mocked type.
- Use one environment for the component and for the test. A nested `RelayEnvironmentProvider` with another environment bypasses the mocks.
- If `loadQuery` runs in a `useEffect`, call `act(() => jest.runAllImmediates())` after the render.
- The v21 guide names the load call `preloadQuery`. The hook-based API in `react-relay` is `loadQuery`.

## Testing Mutations

Cover three paths: optimistic update, success, error.

```tsx
// LikeButton.tsx
import { graphql, useMutation } from 'react-relay';

const mutation = graphql`
  mutation LikeButtonMutation($postId: ID!) {
    likePost(postId: $postId) {
      post { id likeCount viewerHasLiked }
    }
  }
`;

export function LikeButton({ postId, initialCount }: Props) {
  const [commit, inFlight] = useMutation(mutation);
  return (
    <button
      disabled={inFlight}
      onClick={() =>
        commit({
          variables: { postId },
          optimisticResponse: {
            likePost: {
              post: { id: postId, likeCount: initialCount + 1, viewerHasLiked: true },
            },
          },
        })
      }
    >
      Like
    </button>
  );
}
```

### Success

```tsx
test('commits like mutation', async () => {
  const environment = createMockEnvironment();
  render(
    <RelayEnvironmentProvider environment={environment}>
      <LikeButton postId="p_1" initialCount={4} />
    </RelayEnvironmentProvider>
  );

  fireEvent.click(screen.getByRole('button', { name: /like/i }));

  const operation = environment.mock.getMostRecentOperation();
  expect(operation.fragment.variables).toEqual({ postId: 'p_1' });

  act(() => {
    environment.mock.resolve(operation, MockPayloadGenerator.generate(operation, {
      Post: () => ({ id: 'p_1', likeCount: 5, viewerHasLiked: true }),
    }));
  });

  expect(screen.getByRole('button')).not.toBeDisabled();
});
```

### Optimistic

Assert the optimistic state between click and resolve:

```tsx
fireEvent.click(screen.getByRole('button'));
// Button is disabled and store shows optimistic count before the server responds.
expect(screen.getByRole('button')).toBeDisabled();
```

### Error

```tsx
test('rolls back on error', () => {
  const environment = createMockEnvironment();
  render(/* ... */);
  fireEvent.click(screen.getByRole('button'));

  act(() => {
    environment.mock.rejectMostRecentOperation(new Error('Boom'));
  });

  expect(screen.getByRole('button')).not.toBeDisabled();
});
```

## Testing Pagination (`usePaginationFragment`)

Each `loadNext()` fires a new operation. Drive the `pageInfo` via mock resolvers.

```tsx
test('loads next page', async () => {
  const environment = createMockEnvironment();

  render(
    <RelayEnvironmentProvider environment={environment}>
      <Suspense fallback={<div>Loading</div>}>
        <FeedList />
      </Suspense>
    </RelayEnvironmentProvider>
  );

  // Initial page.
  act(() => {
    environment.mock.resolveMostRecentOperation(op =>
      MockPayloadGenerator.generate(op, {
        PageInfo: () => ({ hasNextPage: true, endCursor: 'c1' }),
        ID: (_, g) => `post-${g()}`,
      })
    );
  });

  expect(screen.getAllByTestId('post')).toHaveLength(10);

  fireEvent.click(screen.getByRole('button', { name: /load more/i }));

  // Second page — new operation fires for the pagination query.
  act(() => {
    environment.mock.resolveMostRecentOperation(op =>
      MockPayloadGenerator.generate(op, {
        PageInfo: () => ({ hasNextPage: false, endCursor: 'c2' }),
        ID: (_, g) => `post-${g() + 100}`,
      })
    );
  });

  expect(screen.getAllByTestId('post')).toHaveLength(20);
});
```

Use different `generateId` offsets to avoid colliding record IDs across pages.

## Testing Subscriptions

Subscriptions emit multiple payloads. Use `nextValue` instead of `resolve`.

```tsx
test('receives subscription updates', () => {
  const environment = createMockEnvironment();
  render(
    <RelayEnvironmentProvider environment={environment}>
      <LivePrice symbol="AAPL" />
    </RelayEnvironmentProvider>
  );

  const operation = environment.mock.getMostRecentOperation();

  act(() => {
    environment.mock.nextValue(operation, MockPayloadGenerator.generate(operation, {
      Float: () => 150.0,
    }));
  });
  expect(screen.getByText('150')).toBeInTheDocument();

  act(() => {
    environment.mock.nextValue(operation, MockPayloadGenerator.generate(operation, {
      Float: () => 151.5,
    }));
  });
  expect(screen.getByText('151.5')).toBeInTheDocument();

  act(() => { environment.mock.complete(operation); });
});
```

## Testing Query States: Loading, Error, Data

A query component has 3 states. Test each one with a fresh environment.

```tsx
test('shows the error state when the request fails', async () => {
  const environment = createMockEnvironment();
  render(
    <RelayEnvironmentProvider environment={environment}>
      <ErrorBoundary fallback={<div>Something failed</div>}>
        <Suspense fallback={<div>Loading</div>}>
          <UserCard id="u_1" />
        </Suspense>
      </ErrorBoundary>
    </RelayEnvironmentProvider>
  );

  act(() => {
    environment.mock.rejectMostRecentOperation(new Error('Uh-oh'));
  });

  expect(await screen.findByText('Something failed')).toBeInTheDocument();
});
```

To resolve a query before the first render, register `environment.mock.queueOperationResolver(() => new Error('Uh-oh'))` or a payload resolver and then render.

## Testing Refetch (`useRefetchableFragment`)

Wrap the fragment in a test query as in "Testing Fragments in Isolation". Click the refetch control and resolve the new operation with changed mock data.

```tsx
act(() => {
  environment.mock.resolveMostRecentOperation(op =>
    MockPayloadGenerator.generate(op)
  );
});

fireEvent.click(screen.getByRole('button', { name: /refetch/i }));

act(() => {
  environment.mock.resolveMostRecentOperation(op =>
    MockPayloadGenerator.generate(op, { User: () => ({ name: 'Bob' }) })
  );
});

expect(await screen.findByText('Bob')).toBeInTheDocument();
```

## Testing Mutation and Subscription Callbacks

Code that calls `commitMutation` or `requestSubscription` directly can be tested with `jest.fn` callbacks.

```ts
const onCompleted = jest.fn();
commitMutation(environment, { mutation, variables, onCompleted });
const operation = environment.mock.getMostRecentOperation();
act(() => {
  environment.mock.resolve(operation, MockPayloadGenerator.generate(operation));
});
expect(onCompleted).toHaveBeenCalled();

const onNext = jest.fn();
requestSubscription(environment, { subscription, variables, onNext });
const subscriptionOperation = environment.mock.getMostRecentOperation();
act(() => {
  environment.mock.nextValue(
    subscriptionOperation,
    MockPayloadGenerator.generate(subscriptionOperation)
  );
});
expect(onNext).toHaveBeenCalled();
```

Assert on rendered output or callback arguments. Snapshot assertions (`toMatchSnapshot`) shorten the Relay guide examples but are not the recommended way to assert.

## Full RTL Setup Example

```tsx
// test-utils.tsx
import { ReactNode, Suspense } from 'react';
import { render, RenderOptions } from '@testing-library/react';
import { RelayEnvironmentProvider } from 'react-relay';
import { createMockEnvironment } from 'relay-test-utils';
import type { RelayMockEnvironment } from 'relay-test-utils/lib/RelayModernMockEnvironment';

export function renderWithRelay(
  ui: ReactNode,
  options?: RenderOptions & { environment?: RelayMockEnvironment }
) {
  const environment = options?.environment ?? createMockEnvironment();
  const utils = render(
    <RelayEnvironmentProvider environment={environment}>
      <Suspense fallback={<div data-testid="suspense">Loading</div>}>
        {ui}
      </Suspense>
    </RelayEnvironmentProvider>,
    options
  );
  return { environment, ...utils };
}
```

```tsx
// example.test.tsx
import { screen, act } from '@testing-library/react';
import { MockPayloadGenerator } from 'relay-test-utils';
import { renderWithRelay } from './test-utils';
import { UserCard } from './UserCard';

test('UserCard renders', async () => {
  const { environment } = renderWithRelay(<UserCard id="u_1" />);

  act(() => {
    environment.mock.resolveMostRecentOperation(op =>
      MockPayloadGenerator.generate(op, {
        User: () => ({ name: 'Alice' }),
      })
    );
  });

  expect(await screen.findByText('Alice')).toBeInTheDocument();
});
```

### `jest.config.ts`

```ts
export default {
  testEnvironment: 'jsdom',
  setupFilesAfterEnv: ['@testing-library/jest-dom'],
  transform: { '^.+\\.tsx?$': ['ts-jest', { isolatedModules: true, babelConfig: true }] },
};
```

Relay generates artifacts via `relay-compiler`. Run it before tests. The Jest transform must apply `babel-plugin-relay` (here through ts-jest's `babelConfig`, or use `babel-jest`), which replaces each `graphql` tag with its artifact.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Test hangs / Suspense never resolves | Operation not resolved before assertion | Call `resolveMostRecentOperation` inside `act()` before the assertion. |
| "No operations in flight" | Query not yet issued when resolving | Render first, then inspect `getAllOperations()`; wrap in `act()` so effects flush. |
| `usePreloadedQuery` never completes | Missing `queuePendingOperation` or variable mismatch | Call `queuePendingOperation(query, vars)` with the exact same variables as `loadQuery`. |
| `queueOperationResolver` not firing | Registered after operation was issued | Register the resolver before `loadQuery` or render. |
| Scalar resolvers ignored | Missing `@relay_test_operation` directive | Add `@relay_test_operation` to the query used in tests. |
| Payload shape mismatch errors | Mock resolver returned extra/missing fields for a type | Omit unknown fields; let `MockPayloadGenerator` fill the rest. |
| `act()` warnings in console | State update not wrapped | Wrap the resolve/reject call in `act(() => { ... })`. |
| Duplicate IDs across pagination pages | `generateId()` restarts for each `generate()` call | Offset IDs explicitly per page in the resolver. |
| Cache bleeds between tests | Reused environment | Create a new `createMockEnvironment()` in `beforeEach`. |
| `loadQuery` inside `useEffect` not fetching | Immediate never flushed | `act(() => jest.runAllImmediates())` after render. |
| "Operation not found" in `findOperation` | Predicate too strict or query name differs | Log `getAllOperations().map(o => o.fragment.node.name)` and match exactly. |
| Optimistic update not seen | Asserted after server resolve | Assert immediately after the mutation dispatch, before `resolveMostRecentOperation`. |
| Subscription only emits once | Used `resolve` instead of `nextValue` | Use `nextValue` for each payload; `complete` when done. |
| `nextValue` throws "Expected payload to be an object with a `data` key" | Passed the `data` object without the wrapper | Pass the result of `MockPayloadGenerator.generate`, or `{ data: ... }`. |
| Second queued resolver never runs | The first resolver in the queue returned `null` | Make the first resolver return a payload or an `Error`, or register resolvers in operation order. |
| Mock values look like `<mock-value-for-field-"x">` | Mocked the wrong type | Log the operation JSON and mock the type that owns the field. |
| Deferred data never renders | Used `generate` for a query with `@defer` | Use `generateWithDefer` with `generateDeferredPayload: true` and resolve with the returned array. |
| Client-only fields are empty | `@client` fields are skipped by default | Pass `{ mockClientData: true }` as the third argument of `generate`. |
