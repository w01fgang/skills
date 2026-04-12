# Testing Relay

Reference for testing Relay (hooks-only) components with Jest and React Testing Library using `relay-test-utils`. Covers mock environments, `MockPayloadGenerator`, operation resolution, fragments, mutations, pagination, subscriptions, and preloaded queries.

## Install

```bash
npm install --save-dev relay-test-utils @testing-library/react @testing-library/jest-dom jest
```

`relay-test-utils` ships with the `relay` package family and works with any React Relay version that supports hooks.

## Core APIs

Two exports from `relay-test-utils`:

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
| `queueOperationResolver(resolver)` | Auto-resolve subsequent operations. |
| `queuePendingOperation(query, variables)` | Pre-seed an operation so `usePreloadedQuery` will not suspend indefinitely. |
| `isLoading(request)` | `true` if pending. |
| `cachePayload(request, vars, payload)` | Seed the QueryResponse cache. |
| `clearCache()` | Reset cache. |

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

Without the directive, resolvers by type still work for concrete object types but scalar resolution loses field context.

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

`generateId()` returns a monotonically increasing integer per test run — useful for unique IDs without collisions.

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

Register a resolver that fires for each operation as it is sent:

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
  setupFilesAfterEach: ['@testing-library/jest-dom'],
  transform: { '^.+\\.tsx?$': ['ts-jest', { isolatedModules: true }] },
};
```

Relay generates artifacts via `relay-compiler`. Run it before tests, or use `jest-transform-graphql` to compile on-the-fly.

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
| Duplicate IDs across pagination pages | `generateId()` restarts per resolver call | Offset IDs explicitly per page in the resolver. |
| Cache bleeds between tests | Reused environment | Create a new `createMockEnvironment()` in `beforeEach`. |
| `loadQuery` inside `useEffect` not fetching | Immediate never flushed | `act(() => jest.runAllImmediates())` after render. |
| "Operation not found" in `findOperation` | Predicate too strict or query name differs | Log `getAllOperations().map(o => o.fragment.node.name)` and match exactly. |
| Optimistic update not seen | Asserted after server resolve | Assert immediately after the mutation dispatch, before `resolveMostRecentOperation`. |
| Subscription only emits once | Used `resolve` instead of `nextValue` | Use `nextValue` for each payload; `complete` when done. |
