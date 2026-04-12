# Relay Codemods

Relay ships a small set of first-party codemods as subcommands of the `relay-compiler` binary. They automate mechanical migrations that would otherwise require rewriting thousands of GraphQL documents by hand. This reference also covers community codemods (historically published as `relay-codemod` / `jscodeshift` transforms) for migrating across major Relay versions.

## Compiler-bundled codemods

Since the Rust rewrite, codemods are run through the compiler itself, not a separate package. Discover what's available in your installed version with:

```bash
npx relay-compiler codemod --help
```

General shape:

```bash
npx relay-compiler codemod [OPTIONS] <COMMAND>
# optionally scope to a project in multi-project configs
npx relay-compiler codemod --project=web mark-dangerous-conditional-fragment-spreads
```

Codemods read your `relay.config.json` (or `relay.config.js`) and rewrite `.graphql` tagged literals in-place across the `src` paths declared there. Commit before running — these transforms edit files directly.

### `mark-dangerous-conditional-fragment-spreads` (v19+)

Adds `@dangerously_unaliased_fixme` to every fragment spread that is only conditionally fetched (guarded by `@skip`/`@include`, or matching an abstract type where the runtime type might not implement the fragment's type condition). Use this when upgrading to v19, which enforces `@alias` on such spreads.

```bash
npx relay-compiler codemod mark-dangerous-conditional-fragment-spreads
```

Progressive rollout is supported via a `--rollout` flag paired with the `enforce_fragment_alias_where_ambiguous` feature flag in `relay.config.json`:

```json
{
  "featureFlags": {
    "enforce_fragment_alias_where_ambiguous": { "kind": "disabled" }
  }
}
```

After the codemod runs, flip the flag to `"enabled"` (or remove it) and migrate the `_fixme` sites to real `@alias` annotations over time.

### `remove-unnecessary-required-directives`

Strips `@required` from fields that can never be null in the generated types. Safe targets:

- Fields inside a fragment/operation carrying `@throwOnFieldError`
- Fields under a linked field with `@catch`
- Fields whose schema type became non-null after a server change

The compiler removes a directive only when it can prove the generated TypeScript/Flow output is unchanged.

```bash
npx relay-compiler codemod remove-unnecessary-required-directives
```

Typical workflow: tighten schema nullability on the server, pull new SDL, run this codemod to clean up now-redundant `@required`.

## Upgrading from Flow to TypeScript type emission

Relay emits language-specific types driven by the `language` field per-project in `relay.config.json`:

```json
{
  "projects": {
    "web": {
      "schema": "./schema.graphql",
      "src": "./src",
      "language": "typescript",
      "artifactDirectory": "./src/__generated__"
    }
  }
}
```

Steps to migrate a Flow project:

1. Switch `"language": "flow"` to `"language": "typescript"`.
2. Set a single `artifactDirectory`. This is required for strict fragment-reference types — otherwise `$key` values fall back to `any`.
3. Update the Babel plugin config (`.babelrc`) to point at the same directory:
   ```json
   { "plugins": [["relay", { "artifactDirectory": "./src/__generated__" }]] }
   ```
4. Delete the old Flow `__generated__` directory.
5. Run `npx relay-compiler` to emit `.ts` artifacts.
6. Replace Flow imports: `Foo_user$key`, `Foo_user$data`, `FooQuery$variables` work identically in TS — only the surface syntax (`+readonly` → `readonly`, `?T` → `T | null | undefined`) differs.

There is no first-party codemod for Flow→TS of application code; use `flow-to-ts` or similar third-party tools for the non-Relay portions, then let the compiler regenerate Relay artifacts.

## Upgrading fragment arguments syntax

Older Relay code used JS-level `@relay(variables:)` or ad-hoc prop threading. Modern Relay uses GraphQL-native `@argumentDefinitions` on the fragment and `@arguments` at the spread site:

```graphql
fragment TodoList_list on TodoList
  @argumentDefinitions(
    count: { type: "Int", defaultValue: 10 }
    userID: { type: "ID" }
  ) {
  todoItems(userID: $userID, first: $count) {
    ...TodoItem_item
  }
}

query TodoListQuery($userID: ID!) {
  viewer {
    ...TodoList_list @arguments(userID: $userID)
  }
}
```

No compiler codemod exists for this migration — it is a manual rewrite, usually small in scope. The compiler strips both directives at build time so your server never sees them. If you maintained the classic `Relay.createContainer({ initialVariables })` API, first migrate containers to hooks (below), then fold `initialVariables` into `@argumentDefinitions` default values.

Note: an experimental successor syntax (fragment arguments declared like field arguments) exists behind a feature flag in `graphql-js` and Relay, but `@argumentDefinitions` remains the stable path.

## Adopting `@required`

`@required` is adopted manually, field-by-field — there is no codemod that *adds* it (the compiler cannot infer your null semantics). Typical rollout:

1. Pick an action type per call site:
   - `NONE` — null is expected; no logging.
   - `LOG` — unexpected null; component still renders, logger fires a `missing_required_field.log` event.
   - `THROW` — unrecoverable; component throws, must sit under an error boundary.
2. Apply on leaf fields first:
   ```graphql
   fragment User_profile on User {
     name @required(action: LOG)
     avatar @required(action: LOG) { url @required(action: LOG) }
   }
   ```
3. Parent `@required` must have action severity ≥ its children.
4. When the server tightens nullability on the same field, run `remove-unnecessary-required-directives` to prune redundant annotations.

`@required` is locally scoped to the fragment — different components can handle the same field differently.

## Legacy containers → hooks

Relay's hooks API (`useFragment`, `useLazyLoadQuery`, `usePreloadedQuery`, `useMutation`, `usePaginationFragment`, `useRefetchableFragment`) replaces `createFragmentContainer`, `createPaginationContainer`, `createRefetchContainer`, and `QueryRenderer`. The archived `facebookarchive/relay-codemod` repo contains jscodeshift transforms that handle the mechanical parts of this migration (import rewriting, classic → modern API). It is unmaintained; for new migrations, rewrite call sites by hand — the API surface is small and the type system catches mismatches.

If you're on hooks already, skip this section entirely.

## Writing a custom jscodeshift codemod

For project-specific rewrites (e.g. renaming a hook wrapper, inlining a custom fragment helper), use `jscodeshift` directly. Install: `npm i -D jscodeshift @types/jscodeshift`.

Minimal transform that renames `useFragment` imports from a wrapper module to the official package:

```js
// rewrite-useFragment.js
module.exports = function transformer(file, api) {
  const j = api.jscodeshift;
  const root = j(file.source);

  root
    .find(j.ImportDeclaration, { source: { value: "./relay-wrappers" } })
    .forEach((path) => {
      const spec = path.value.specifiers.find(
        (s) => s.imported && s.imported.name === "useFragment"
      );
      if (!spec) return;
      path.value.source = j.literal("react-relay");
    });

  return root.toSource({ quote: "single" });
};
```

Run it:

```bash
npx jscodeshift -t ./rewrite-useFragment.js --extensions=ts,tsx ./src
```

For GraphQL-literal rewrites, parse the template body yourself (`graphql` package's `parse`/`print`) rather than regex — tagged template edits are brittle otherwise.

## Available codemods — when to run

| Codemod | Version | Run when |
|---|---|---|
| `mark-dangerous-conditional-fragment-spreads` | v19+ | Upgrading to v19; before enabling `enforce_fragment_alias_where_ambiguous`. |
| `remove-unnecessary-required-directives` | v16+ | After the server tightens field nullability, or after adopting `@throwOnFieldError` / `@catch`. |
| `relay-codemod` (archived jscodeshift) | pre-hooks | Only if still on `createFragmentContainer` / classic Relay; prefer manual rewrite. |
| Custom jscodeshift transform | any | Project-specific renames, import rewrites, bespoke cleanups. |

Always: commit before running, inspect the diff, run `npx relay-compiler` and your test suite after.
