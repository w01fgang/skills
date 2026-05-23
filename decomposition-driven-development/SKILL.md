---
name: decomposition-driven-development
description: Use when building a non-trivial feature, component, screen, or module from scratch.
---

# Decomposition-Driven Development

## Overview

Build features by decomposing them into the smallest independently testable units, **freezing each unit's contract (signature + tests) before writing any implementation**, then building leaf units first — in parallel where they're independent — and composing upward into the feature.

Why contracts first: parallel implementation is only safe when interfaces are fixed. Once a unit's signature and tests exist, that unit can be built in isolation (by a subagent or in sequence) without coordinating with the others, and it's reusable because it's defined by its interface, not by its caller.

## The Workflow

1. **Document** — write the feature's observable behavior (no filler), before any design
2. **Decompose** — split the feature into single-responsibility units
3. **Specify** — write each unit's contract (signature, responsibility, requirements, deps)
4. **Graph** — list dependencies, compute parallel build waves
5. **Test** — write failing tests against each contract
6. **Implement** — build wave by wave; units in a wave run in parallel
7. **Compose** — wire units into the feature; verify behavior matches the docs

Do not start step N+1 until step N is done for the whole feature. Resist implementing during decomposition.

---

### Step 1 — Document (behavior first)

First read the surrounding code the feature must fit — existing APIs, patterns, and tests; write no implementation yet. Then document how the feature behaves from the outside — what the user does and what they observe. This is the behavior contract for the whole feature; the integration tests in Step 7 assert exactly what it claims.

Document only observable behavior:

- **What it does** — one line.
- **Behaviors** — `given <state> / when <action> → <observable result>`, one per line.
- **States** — loading, empty, populated, error.
- **Edge cases & errors** — what the user sees when something goes wrong.

Write it with no "water":

- No filler adjectives ("powerful", "seamless", "robust", "simply", "just").
- No marketing or tutorial tone.
- No implementation detail — docs say *what the user observes*, not *how it works*.
- No restating the obvious or narrating the code.

Test: if a line doesn't change what a reader expects the feature to do, delete it.

### Step 2 — Decompose

Split until each unit has one responsibility and a clean interface. Decomposition targets (frontend example):

- **Pure functions** — logic with no I/O or state: formatting, validation, calculation, transforms, reducers. `input → output`.
- **Hooks** — stateful or effectful logic: data fetching, subscriptions, derived state, event wiring, timers.
- **Presentational components** — `props → UI`. No business logic, no data fetching.
- **Container component** — composes hooks + presentational children. This is the feature root; built last.

Heuristics:

- Describable as "given X, return Y" with no side effects → **pure function**.
- Holds state or touches the outside world → **hook**.
- Only renders from props → **presentational component**.
- Used by 2+ units → its own unit (reusable).
- Needs more than one sentence to describe its responsibility → split further.

The same shape applies outside frontend: pure functions = logic, hooks = stateful services/clients, presentational = formatters/serializers, container = orchestrator.

### Step 3 — Specify (contracts)

For **every** unit, write a contract before implementing. Freeze signatures here — changing them later breaks parallelism and forces dependents to be reworked.

```
### <unitName>   (function | hook | component)
Signature:    (args: T) => R   |   props: { ... }   |   () => { value, ... }
File:         <path where it lives>     Test:  <path of its test file>
Responsibility: <one sentence>
Requirements:
  - <observable behavior 1>
  - <observable behavior 2 / edge case>
Depends on:   <unit, unit>   (or: none — leaf)
```

The contract is the single source of truth a parallel implementer builds against. Requirements must be observable assertions, not implementation notes. Keep all contracts + the dependency graph in one shared file (e.g. `PLAN.md`) so every parallel implementer reads the same fixed paths and signatures.

### Step 4 — Graph dependencies

List edges as `[unit, dependency]`, then compute build waves with the bundled script:

```bash
# path is relative to this skill's directory; locate with: find . -name plan_waves.py
scripts/plan_waves.py graph.json
```

`graph.json`:

```json
{"edges": [["FeatureRoot","useData"], ["FeatureRoot","ItemList"], ["ItemList","ItemRow"], ["ItemRow","formatPrice"]]}
```

Output lists ordered waves. **Units in the same wave have no inter-dependencies → implement them in parallel.** A reported cycle means the decomposition is wrong — break it (extract a shared leaf, invert a dependency, or pass a callback/interface instead of a direct import) before continuing.

### Step 5 — Write tests

Write tests from each contract's **Requirements** before any implementation exists. First create signature-only stubs (an empty function/hook/component matching the contract) so tests import and run — they must fail on assertions, not on missing modules. Each unit is tested in isolation; mock its declared dependencies.

- Pure function → input/output assertions + edge cases.
- Hook → `renderHook`, assert state transitions; mock data sources.
- Component → render with props, assert output; mock declared child units only.

Tests fail now on assertions (not import errors). That red bar is the definition of done for each unit.

### Step 6 — Implement (parallel)

Build wave by wave, starting with leaves. Within a wave, units are independent, so dispatch them concurrently:

- **In-session parallel** — one subagent per unit, briefed with that unit's contract + tests. Pairs with the `subagent-driven-development` skill if available. Each subagent's done-criterion is its own tests passing.
- A unit may only use the **public interface** of its declared dependencies — never reach into another unit's internals.
- Advance to the next wave only after the current wave's tests are green.

### Step 7 — Compose

Wire units into the container / feature root. Add **integration tests** that assert the behaviors documented in Step 1 (golden path + key edge cases) — distinct from the unit tests, which covered internals. For UI, verify in a browser, not just the test runner. Reconcile docs with reality: if the implementation drifted from the documented behavior, fix the implementation. Only update the Step 1 doc when the behavior change was intended and approved — never edit the doc just to paper over an accidental drift.

---

## Worked example

A product list that fetches items and shows each with a formatted price.

**Step 1 — Document**

- Shows a list of products, each with name + price.
- given loading → spinner.
- given empty result → "No products".
- given items → one row per product; price shown as `$1,234.50`.
- given fetch error → "Couldn't load products".

**Step 2 — Decompose**

- `formatPrice` — pure function
- `useProducts` — hook (fetch + load state)
- `ProductRow` — presentational
- `ProductList` — presentational
- `ProductsScreen` — container (feature root)

**Step 3 — Contracts** (in `PLAN.md`)

Shared type: `type Product = { id: string; name: string; priceCents: number }`.

```
### formatPrice   (function)
Signature:    (cents: number) => string
File: src/products/formatPrice.ts   Test: src/products/formatPrice.test.ts
Responsibility: render an integer cent amount as a USD string.
Requirements:
  - 123450 → "$1,234.50"
  - 0 → "$0.00"
Depends on: none — leaf

### useProducts   (hook)
Signature:    () => { status: "loading" | "error" | "ready"; products: Product[] }
File: src/products/useProducts.ts   Test: src/products/useProducts.test.ts
Responsibility: fetch products and expose load state.
Requirements:
  - starts at status "loading"
  - resolves with items → status "ready", products populated
  - resolves empty → status "ready", products []
  - rejects → status "error", products []
Depends on: none — leaf

### ProductRow   (component)
Signature:    props: { product: Product }
File: src/products/ProductRow.tsx   Test: src/products/ProductRow.test.tsx
Responsibility: render one product's name + formatted price.
Requirements:
  - renders product.name
  - given priceCents 123450 → renders "$1,234.50"
Depends on: formatPrice

### ProductList   (component)
Signature:    props: { products: Product[] }
File: src/products/ProductList.tsx   Test: src/products/ProductList.test.tsx
Responsibility: render a ProductRow per product, or an empty message.
Requirements:
  - empty array → renders "No products"
  - N products → renders N rows
Depends on: ProductRow

### ProductsScreen   (component)
Signature:    () => JSX.Element
File: src/products/ProductsScreen.tsx   Test: src/products/ProductsScreen.test.tsx
Responsibility: wire useProducts to ProductList; handle load + error states.
Requirements:
  - status "loading" → spinner
  - status "error" → "Couldn't load products"
  - status "ready" → ProductList with the products
Depends on: useProducts, ProductList
```

Every decomposed unit gets its own contract — no prose shortcuts.

**Step 4 — Graph → waves**

```json
{"edges": [["ProductsScreen","useProducts"], ["ProductsScreen","ProductList"], ["ProductList","ProductRow"], ["ProductRow","formatPrice"]]}
```

```
leaves (parallel): formatPrice, useProducts
wave 1 (parallel): ProductRow
wave 2 (parallel): ProductList
wave 3 (parallel): ProductsScreen
```

**Step 5 — Stub + test** (red bar)

```ts
// formatPrice.ts — signature-only stub so the test imports and runs
export const formatPrice = (cents: number): string => "";

// formatPrice.test.ts
test("formats cents as USD", () => {
  expect(formatPrice(123450)).toBe("$1,234.50");
});
```

(One unit shown — stub + test every contract this way before any implementation.)

**Steps 6–7** — implement the leaves (`formatPrice`, `useProducts`) in parallel, then `ProductRow`, then `ProductList`, then `ProductsScreen`. Compose into the screen, then add integration tests asserting the Step 1 behaviors:

```tsx
// ProductsScreen.test.tsx — integration, asserts documented behavior
test("shows products once loaded", async () => {
  mockGetProducts([{ id: "1", name: "Widget", priceCents: 123450 }]);
  render(<ProductsScreen />);
  expect(await screen.findByText("Widget")).toBeInTheDocument();
  expect(screen.getByText("$1,234.50")).toBeInTheDocument();
});
```

---

## Anti-patterns

- **Coding before contracts + tests exist** → parallel work collides; rework. Contracts first, always.
- **Units sharing mutable state** → not independently testable. Pass data via params/props/return values instead.
- **Changing a signature mid-build** → silently invalidates dependents. Re-spec the contract and re-graph instead.
- **One giant "smart" component** → no reuse, no parallelism. Extract hooks and pure functions out of it.
- **Skipping the graph** → wrong build order; a subagent gets blocked waiting on an unbuilt dependency.
- **Vague requirements** ("works correctly") → untestable. Each requirement must be an assertion that can fail.
- **"Water" in docs** → filler, marketing, or implementation detail in behavior docs. Document only what the user observes; delete lines that don't change a reader's expectations.
- **Docs that drift from behavior** → behavior changed but the doc didn't (or vice versa). The Step 1 doc and the Step 7 integration tests must describe the same behaviors.
