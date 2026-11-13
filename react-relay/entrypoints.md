# Relay EntryPoints

An EntryPoint is a lightweight object. It holds the components to load (as calls to `JSResource`) and the queries to load before a route, popover or other piece of conditionally loaded UI renders. `loadEntryPoint` and `EntryPointContainer` implement the "render-as-you-fetch" pattern.

## What is an EntryPoint?

- An EntryPoint has a `getPreloadProps` method. It takes the EntryPoint params.
- All queries required for the initial render of a piece of UI belong in the EntryPoint of that UI.
- An EntryPoint can contain queries and other EntryPoints.
- If `getPreloadProps` returns an object with an `extraProps` property, Relay passes those props to the EntryPoint component as `extraProps`.
- A query or an EntryPoint is lazy loaded if the request for the data occurs at render time. Lazy loaded queries and EntryPoints have performance downsides, are vulnerable to over- and under-fetching, and can render components with null data. Avoid them.

## JSResource

`JSResource` is an API that loads a React component on demand. A direct import or require bundles the component with the first require. `JSResource` is safe to use in EntryPoint files. See [the npm module](https://www.npmjs.com/package/jsresource).

## Component props

The EntryPoint component receives these props:

- `queries` — the preloaded queries (type parameter `TPreloadedQueries`).
- `entryPoints` — the nested EntryPoints (type parameter `TPreloadedEntryPoints`).
- `extraProps` — the `extraProps` property of the `getPreloadProps` result (type parameter `TExtraProps`).
- `props` — the runtime props that `EntryPointContainer` passes down (type parameter `TRuntimeProps`).

## `useEntryPointLoader` hook

The hook keeps an EntryPoint reference in state and disposes of it when it is not accessible through state. This avoids data leaking into the Relay store.

```js
const {useEntryPointLoader, EntryPointContainer} = require('react-relay');

const ComponentEntryPoint = require('Component.entrypoint');

function EntryPointRevealer(): React.MixedElement {
  const environmentProvider = useMyEnvironmentProvider();
  const [
    entryPointReference,
    loadEntryPoint,
    disposeEntryPoint,
  ] = useEntryPointLoader(environmentProvider, ComponentEntryPoint);

  return (
    <>
      {
        entryPointReference == null && (
          <Button onClick={() => loadEntryPoint({})}>
            Click to reveal the contents of the EntryPoint
          </Button>
        )
      }
      {
        entryPointReference != null && (
          <>
            <Button onClick={disposeEntryPoint}>
              Click to hide and dispose the EntryPoint.
            </Button>
            <Suspense fallback="Loading...">
              <EntryPointContainer
                entryPointReference={entryPointReference}
                props={{}}
              />
            </Suspense>
          </>
        )
      }
    </>
  );
}
```

Arguments:

- **`environmentProvider`** — an object with a `getEnvironment` method that returns a Relay environment.
- **`EntryPoint`** — the EntryPoint, usually acquired by importing a `.entrypoint.js` file.

Return value, a tuple:

- **`entryPointReference`** — the EntryPoint reference, or `null`.
- **`loadEntryPoint(params)`** — loads an EntryPoint. The result is available as `entryPointReference`. It disposes of the EntryPoint that an earlier call loaded. `params` is the `TEntryPointParams` value that Relay passes to `getPreloadProps`. It may throw an error if called during React's render phase.
- **`disposeEntryPoint()`** — sets `entryPointReference` to `null` and calls `.dispose()` on it. Type `() => void`. Do not call it during React's render phase.

Notes:
- Call `loadEntryPoint` from an event handler or an effect. The docs state that it can throw during React's render phase. The v20.1.1 and v21.0.1 source of `loadEntryPoint.js` has no render-phase check, so a call in render creates a new undisposed ref on every render.
- When `loadEntryPoint` runs, each query of the EntryPoint loads its query data and query AST. Relay writes the data to the store when both the AST and the data are available. This differs from `prepareEntryPoint_DEPRECATED`, which writes the data only when `usePreloadedQuery` renders the query.
- The Relay store retains the queries of the EntryPoint reference. Data stays in the store until `.dispose()` runs on the reference. After that, the data can be garbage collected.

## `loadEntryPoint` imperative

`loadEntryPoint` is designed for use with `EntryPointContainer`. Prefer `useEntryPointLoader` when possible, because it disposes of EntryPoint references for you.

```js
const EntryPoint = require('MyComponent.entrypoint.js');

// Generally, your component should access the environment from the React context,
// and pass that environment to this function.
const getEntrypointReference = environment => loadEntryPoint(
  { getEnvironment: () => environment },
  EntryPoint,
  {id: '4'},
);

// later: pass entryPointReference to EntryPointContainer
// Note that EntryPoint references should have .dispose() called on them,
// which is missing in this example.
```

Arguments:

- **`environmentProvider`** — a provider for the Relay Environment instance that executes the request. Inside a React component, use the environment from `useRelayEnvironment`.
- **`EntryPoint`** — the EntryPoint to load.
- **`entryPointParams`** — the parameters that Relay passes to the `getPreloadProps` method of the EntryPoint.

Return value: an EntryPoint reference with the property `dispose`.

- `dispose` releases the query references that this EntryPoint loaded, including nested EntryPoints. The store releases them, so Relay can garbage collect their data.
- The docs state that only `dispose` is a stable property of the reference. The format of the other properties is unstable. Pass the reference to `EntryPointContainer`.

Behavior:

- `loadEntryPoint` loads the query data and query AST of each associated query. Relay writes the data to the store when both are available.
- References from `loadEntryPoint` leak data to the Relay store unless `.dispose()` runs on them when nothing references them any longer.
- `loadEntryPoint` may throw an error if called during React's render phase.

## `<EntryPointContainer />`

A React component that renders a preloaded EntryPoint.

```js
function EntryPointContainer({
  entryPointReference,
  props,
}: {
  +entryPointReference: PreloadedEntryPoint<TEntryPointComponent>,
  +props: TRuntimeProps,
}): ReactElement
```

Props:
- **`entryPointReference`** — the value from `loadEntryPoint` or from the `useEntryPointLoader` hook.
- **`props`** — additional runtime props that Relay passes to the component.

## Disposing EntryPoint refs

- `useEntryPointLoader` disposes of the reference when it is not accessible through state.
- A reference from `loadEntryPoint` needs a `.dispose()` call when nothing references it any longer.
- After `.dispose()`, the data of the associated queries can be garbage collected.
- Do not call `disposeEntryPoint` during React's render phase.
