# Relay EntryPoints

EntryPoints bundle **code** and **data** for a unit of UI (a route, modal, popover) so both can be preloaded in parallel before the component renders. They extend the render-as-you-fetch pattern of `useQueryLoader`/`usePreloadedQuery` with parallel **code** loading and composition of nested units.

## What is an EntryPoint?

An EntryPoint is a lightweight object describing:

- **`root`** — a `JSResource` pointing to the component module to render
- **`getPreloadProps(params)`** — pure function mapping route params to the queries (and nested entrypoints) that must be preloaded before rendering
- Optionally nested **`entryPoints`** — other EntryPoints to load in parallel

When loaded, Relay fires the queries *and* starts downloading the component chunk simultaneously. The component renders as soon as both are ready.

### When to use over `useQueryLoader`

Use `useQueryLoader` + `usePreloadedQuery` when the rendering component is already in the JS bundle. Use EntryPoints when you also want to **code-split** the rendering component, or when a unit of UI composes multiple code-split children each with their own queries.

## JSResource: code splitting

`JSResource` is a thin wrapper around dynamic `import()` that the EntryPoint APIs understand. It's not shipped with Relay — projects typically define their own or use one from their router. The canonical shape:

```tsx
// JSResource.ts
type Loader<T> = () => Promise<{default: T}>;

export interface JSResourceReference<T> {
  load(): Promise<T>;
  get(): T | undefined; // synchronous access once loaded
  getModuleIfRequired(): T | undefined;
}

export function JSResource<T>(
  moduleId: string,
  loader: Loader<T>,
): JSResourceReference<T> {
  let promise: Promise<T> | undefined;
  let resolved: T | undefined;
  return {
    load() {
      if (!promise) {
        promise = loader().then(m => {
          resolved = m.default;
          return resolved;
        });
      }
      return promise;
    },
    get: () => resolved,
    getModuleIfRequired: () => resolved,
  };
}
```

Using it:

```tsx
import {JSResource} from './JSResource';
import type UserProfileType from './UserProfile';

export const UserProfileResource = JSResource<typeof UserProfileType>(
  'UserProfile',
  () => import('./UserProfile'),
);
```

## Defining an EntryPoint

An EntryPoint is defined in its own file, conventionally named `*.entrypoint.ts`. It must import **types only** from the component (never the component itself) to keep the entrypoint module tiny.

```tsx
// UserProfile.entrypoint.ts
import type {EntryPoint} from 'react-relay';
import type UserProfile from './UserProfile';
import type UserProfileQueryType from './__generated__/UserProfileQuery.graphql';

import {JSResource} from './JSResource';
import UserProfileQuery from './__generated__/UserProfileQuery.graphql';

type Params = {userId: string};

export const UserProfileEntryPoint: EntryPoint<typeof UserProfile, Params> = {
  root: JSResource('UserProfile', () => import('./UserProfile')),
  getPreloadProps({userId}) {
    return {
      queries: {
        userProfileQuery: {
          parameters: UserProfileQuery,
          variables: {id: userId},
          options: {fetchPolicy: 'store-or-network'},
        },
      },
    };
  },
};
```

The component receives the preloaded queries in a `queries` prop keyed by the names from `getPreloadProps`:

```tsx
// UserProfile.tsx
import type {EntryPointComponent} from 'react-relay';
import type UserProfileQueryType from './__generated__/UserProfileQuery.graphql';

import {graphql, usePreloadedQuery} from 'react-relay';

type Queries = {userProfileQuery: UserProfileQueryType};
type RuntimeProps = {highlight?: boolean};

const UserProfile: EntryPointComponent<Queries, {}, RuntimeProps> = ({
  queries,
  props,
}) => {
  const data = usePreloadedQuery(
    graphql`
      query UserProfileQuery($id: ID!) {
        user(id: $id) {
          name
          avatarUrl
        }
      }
    `,
    queries.userProfileQuery,
  );
  return (
    <section data-highlight={props.highlight}>
      <h1>{data.user?.name}</h1>
    </section>
  );
};

export default UserProfile;
```

## Nested EntryPoints

`getPreloadProps` can also return `entryPoints`. Each nested entrypoint is loaded in parallel with the parent's queries, and arrives in the component as a `PreloadedEntryPoint` ready to be rendered with `<EntryPointContainer>`.

```tsx
// Dashboard.entrypoint.ts
import type {EntryPoint} from 'react-relay';
import type Dashboard from './Dashboard';

import {JSResource} from './JSResource';
import DashboardQuery from './__generated__/DashboardQuery.graphql';
import {UserProfileEntryPoint} from './UserProfile.entrypoint';
import {ActivityFeedEntryPoint} from './ActivityFeed.entrypoint';

type Params = {userId: string};

export const DashboardEntryPoint: EntryPoint<typeof Dashboard, Params> = {
  root: JSResource('Dashboard', () => import('./Dashboard')),
  getPreloadProps({userId}) {
    return {
      queries: {
        dashboardQuery: {
          parameters: DashboardQuery,
          variables: {id: userId},
        },
      },
      entryPoints: {
        profile: {
          entryPoint: UserProfileEntryPoint,
          entryPointParams: {userId},
        },
        feed: {
          entryPoint: ActivityFeedEntryPoint,
          entryPointParams: {userId, limit: 20},
        },
      },
    };
  },
};
```

The parent component renders each child with `EntryPointContainer`:

```tsx
// Dashboard.tsx
import type {EntryPointComponent} from 'react-relay';
import type DashboardQueryType from './__generated__/DashboardQuery.graphql';
import type UserProfile from './UserProfile';
import type ActivityFeed from './ActivityFeed';

import {Suspense} from 'react';
import {EntryPointContainer, graphql, usePreloadedQuery} from 'react-relay';

type Queries = {dashboardQuery: DashboardQueryType};
type NestedEntryPoints = {
  profile: typeof UserProfile;
  feed: typeof ActivityFeed;
};

const Dashboard: EntryPointComponent<Queries, NestedEntryPoints> = ({
  queries,
  entryPoints,
}) => {
  const data = usePreloadedQuery(
    graphql`
      query DashboardQuery($id: ID!) {
        user(id: $id) { displayName }
      }
    `,
    queries.dashboardQuery,
  );
  return (
    <div>
      <h1>{data.user?.displayName}</h1>
      <Suspense fallback="Loading profile...">
        <EntryPointContainer
          entryPointReference={entryPoints.profile}
          props={{highlight: true}}
        />
      </Suspense>
      <Suspense fallback="Loading feed...">
        <EntryPointContainer
          entryPointReference={entryPoints.feed}
          props={{}}
        />
      </Suspense>
    </div>
  );
};

export default Dashboard;
```

## `useEntryPointLoader` hook

The hook-based way to load an entrypoint. It owns the ref's lifetime and disposes on unmount or reload.

```tsx
const [entryPointRef, loadEntryPoint, disposeEntryPoint] =
  useEntryPointLoader(environmentProvider, DashboardEntryPoint);
```

- **`environmentProvider`** — `{getEnvironment(): Environment}`. Usually a stable module-level object.
- **`entryPointRef`** — `PreloadedEntryPoint | null`. Pass to `EntryPointContainer`.
- **`loadEntryPoint(params)`** — begins loading code + data. Disposes any prior ref automatically.
- **`disposeEntryPoint()`** — releases retained query data. Do not call during render.

Example — loading on a button click:

```tsx
import {Suspense} from 'react';
import {EntryPointContainer, useEntryPointLoader} from 'react-relay';
import {environmentProvider} from './environment';
import {UserProfileEntryPoint} from './UserProfile.entrypoint';

function ProfileLauncher({userId}: {userId: string}) {
  const [ref, load, dispose] = useEntryPointLoader(
    environmentProvider,
    UserProfileEntryPoint,
  );
  return (
    <>
      <button onClick={() => load({userId})}>Open profile</button>
      {ref != null && (
        <dialog open>
          <button onClick={dispose}>Close</button>
          <Suspense fallback="Loading...">
            <EntryPointContainer entryPointReference={ref} props={{}} />
          </Suspense>
        </dialog>
      )}
    </>
  );
}
```

Notes:
- `loadEntryPoint` throws if invoked during render — fire it from an effect or event handler.
- Data is written to the store when both AST and query response are available and stays retained until disposal.

## `loadEntryPoint` imperative

`loadEntryPoint` is the raw function behind the hook. Prefer the hook in components; use `loadEntryPoint` from routers or event handlers that outlive a single component's lifecycle.

```tsx
import {loadEntryPoint, type PreloadedEntryPoint} from 'react-relay';
import {environmentProvider} from './environment';
import {DashboardEntryPoint} from './Dashboard.entrypoint';
import type Dashboard from './Dashboard';

const ref: PreloadedEntryPoint<typeof Dashboard> = loadEntryPoint(
  environmentProvider,
  DashboardEntryPoint,
  {userId: 'u_42'},
);

// Later, when no longer rendered:
ref.dispose();
```

The returned ref has `.dispose()` which releases retained store data. Until disposed, the data remains and will not be garbage collected.

## `<EntryPointContainer />`

Renders a preloaded EntryPoint.

```tsx
<EntryPointContainer
  entryPointReference={ref}
  props={{highlight: true}}
/>
```

Props:
- **`entryPointReference`** — from `loadEntryPoint` or `useEntryPointLoader`.
- **`props`** — runtime props forwarded to the component's `props` argument (typed as `TRuntimeProps`).

The container suspends until both the code chunk and query data are ready, so wrap it in `<Suspense>`.

## Router integration

The strongest use case: preload code + data when a route match is detected, before the destination component mounts.

```tsx
// routes.ts
import type {EntryPoint} from 'react-relay';
import {DashboardEntryPoint} from './Dashboard.entrypoint';
import {UserProfileEntryPoint} from './UserProfile.entrypoint';

export const routes = [
  {path: '/dashboard/:userId', entryPoint: DashboardEntryPoint},
  {path: '/users/:userId', entryPoint: UserProfileEntryPoint},
] satisfies Array<{path: string; entryPoint: EntryPoint<any, any>}>;
```

```tsx
// RouterHost.tsx
import {Suspense, useEffect, useState} from 'react';
import {EntryPointContainer, loadEntryPoint} from 'react-relay';
import {environmentProvider} from './environment';
import {matchRoute} from './matchRoute';

type Match = {
  ref: ReturnType<typeof loadEntryPoint>;
  params: Record<string, string>;
};

function RouterHost({location}: {location: string}) {
  const [match, setMatch] = useState<Match | null>(null);

  useEffect(() => {
    const matched = matchRoute(location);
    if (!matched) return;
    const ref = loadEntryPoint(
      environmentProvider,
      matched.entryPoint,
      matched.params,
    );
    setMatch({ref, params: matched.params});
    return () => ref.dispose();
  }, [location]);

  if (!match) return null;
  return (
    <Suspense fallback="Loading...">
      <EntryPointContainer
        entryPointReference={match.ref}
        props={match.params}
      />
    </Suspense>
  );
}
```

Prefetching on link hover:

```tsx
function PrefetchLink({
  to,
  entryPoint,
  params,
  children,
}: {
  to: string;
  entryPoint: EntryPoint<any, any>;
  params: any;
  children: React.ReactNode;
}) {
  const prefetch = () => {
    const ref = loadEntryPoint(environmentProvider, entryPoint, params);
    // Store and dispose after navigation completes, or on timeout.
    setTimeout(() => ref.dispose(), 30_000);
  };
  return (
    <a href={to} onMouseEnter={prefetch} onFocus={prefetch}>
      {children}
    </a>
  );
}
```

## Disposing EntryPoint refs

Every successful `loadEntryPoint` retains query data in the store. You **must** dispose:

- `useEntryPointLoader` disposes automatically on unmount, on re-load, and via the returned `disposeEntryPoint`.
- `loadEntryPoint` must be manually disposed via `ref.dispose()` when the ref is no longer rendered.

Rules:
- Never call `dispose` during React render.
- Calling `dispose` on an already-disposed ref is a no-op but don't rely on it — track lifetime in effect cleanups.
- After disposal, the ref's data becomes eligible for GC; do not render an EntryPointContainer with a disposed ref.

## EntryPoint vs `useQueryLoader`

| Aspect | `useQueryLoader` + `usePreloadedQuery` | EntryPoints |
|--------|----------------------------------------|-------------|
| Preloads query data | Yes | Yes |
| Preloads component code | No (component must be imported) | Yes, via `JSResource` |
| Composition of nested code-split units | Manual (`useQueryLoader` per child) | Built-in via `entryPoints` in `getPreloadProps` |
| API surface | 1 hook + 1 hook | 1 hook + 1 component + definition file |
| Typical caller | Any component | Router, route boundary, modal opener |
| Runtime props channel | N/A | `<EntryPointContainer props>` |
| Setup cost | Low | Medium (definition + JSResource infra) |
| Best for | Single known query before render | Route-level units with code + data + children |
| Disposal | Automatic via hook | Automatic via hook, manual via `loadEntryPoint` |
| Param shape | Query variables | Arbitrary params mapped by `getPreloadProps` |

Rule of thumb: reach for `useQueryLoader` for a single query inside an already-loaded component; reach for EntryPoints when the unit of UI is itself code-split or composes multiple code-split children.
