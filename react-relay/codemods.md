# Relay Codemods

The Relay compiler makes changes across the source files of your projects with codemods. The compiler `codemod` command lists the available codemods.

## Compiler-bundled codemods

```
> relay codemod --help
Apply codemod (verification with auto-applied fixes)

Usage: relay codemod [OPTIONS] [CONFIG] <COMMAND>

Commands:
  mark-dangerous-conditional-fragment-spreads  Marks unaliased conditional fragment spreads as @dangerously_unaliased_fixme
  remove-unnecessary-required-directives       Removes @required directives from non-null fields within @throwOnFieldError fragments and operations.
  fix-all                                      Runs all Relay compiler transforms and fixes all fixable diagnostics
  help                                         Print this message or the help of the given subcommand(s)

Arguments:
  [CONFIG]  Compile using this config file. If not provided, searches for a config in package.json under the `relay` key or `relay.config.json` files among other up from the current working directory

Options:
  -p, --project <project>  Compile only this project. You can pass this argument multiple times. to compile multiple projects. If excluded, all projects will be compiled
  -h, --help               Print help
```

Options (`relay-bin/src/main.rs`, v21):

| Option | Meaning |
|---|---|
| `-p`, `--project <name>` | Run for 1 project. Repeat the option for several projects. Without it, all projects run. |
| `[CONFIG]` | Optional config file path. Without it, the compiler searches `package.json` (`relay` key) and `relay.config.json` upward from the working directory. |


On v20, only `mark-dangerous-conditional-fragment-spreads` and `remove-unnecessary-required-directives` exist (v20 `AvailableCodemod`). The v20 docs `--help` output lists only the first one.

### `mark-dangerous-conditional-fragment-spreads` (v19+)

Adds `@dangerously_unaliased_fixme` to every fragment spread that is only conditionally fetched (guarded by `@skip`/`@include`, or matching an abstract type where the runtime type might not implement the fragment's type condition). Without `@alias`, the generated Flow or TypeScript types cannot reflect the nullability of such a spread. Use this when upgrading to v19, which enforces `@alias` on such spreads. After the codemod, enable the `enforce_fragment_alias_where_ambiguous` feature flag so that future ambiguous fragment spreads must be aliased. On v20.1.1 a config without a `featureFlags` object leaves the enforcement flag `disabled`; set `enforce_fragment_alias_where_ambiguous` explicitly.

The optional `--rollout-percentage` parameter (shorthand `-r`) works together with the `enforce_fragment_alias_where_ambiguous` feature flag in rollout mode. It allows progressive codemod and enforcement of this validation. Both v20 and v21 define `--rollout-percentage` / `-r` in `relay-codemod/src/codemod.rs`. The v20 docs page spells the option `--rollout`; the source wins.

### `remove-unnecessary-required-directives`

Removes `@required` from non-null fields within `@throwOnFieldError` fragments and operations, or linked fields with `@catch`. The compiler removes a directive only when it is certain that the directive does not change the generated types for the data being fetched.

### `fix-all` (v21+)

Runs all Relay compiler transforms and applies the fix for each fixable diagnostic. Run it after each Relay version upgrade to repair the issues that the compiler now flags:

```sh
relay codemod fix-all
```

In v21 it rewrites `@RelayResolver` docblocks to `@relayType` / `@relayField`.

## Upgrading to v21

- **TypeScript types ship in the packages.** `relay-runtime` and `react-relay` include `.d.ts` files (present from 21.0.1). Remove `@types/relay-runtime` and `@types/react-relay`. Named ESM imports work in `.mjs` files.
- **Flow users:** generated types use `(expr as Type)` casts (Flow 0.250.0 or later), `ReadonlyArray`, `unknown` and `NonNullable`. Re-run the compiler to regenerate all artifacts.
- **`@live_query` is removed.** Use `@client_polling(interval: ...)` for polling or `@live` for server-pushed updates.
- **Resolver docblocks:** `@RelayResolver` becomes `@relayType` / `@relayField`. The verbose legacy tags (`@onType`, `@onInterface`, `@fieldName`, `@edgeTo`) are removed. Run `codemod fix-all`, or enable the `allow_legacy_relay_resolver_tag` feature flag to keep the old tag for now.
- **`@oneOf` inputs** generate a discriminated union type that permits 1 property at a time. Set `"oneOfType": "ignore"` in the compiler config to keep the object type with all-optional fields. (The v21 release notes name the value `"relaxed"`; the compiler config schema accepts `"strict"` and `"ignore"`.)
- **Compiler flags:** `relay-compiler --validate` exits with a non-zero code when an artifact is out of date, and writes nothing. `relay-compiler --noWatchman` (21.0.1) finds files by directory traversal; `--watch` needs watchman. (The compiler docs page spells the flag `--no-watchman`; the 21.0.1 CLI defines its flags in camel case.)
- **Experimental React Server Components entry points:** `react-relay/rsc_EXPERIMENTAL` exports `createServerEnvironment`, which returns `serverFetchQuery`, `serverReadFragment` and `serverPreloadQuery`. `react-relay/rsc-client_EXPERIMENTAL` exports `useQueryFromServer`. The API can change between versions.

## Available codemods — when to run

| Codemod | Version | Run when |
|---|---|---|
| `mark-dangerous-conditional-fragment-spreads` | v19+ | Upgrading to v19; before enabling `enforce_fragment_alias_where_ambiguous`. |
| `remove-unnecessary-required-directives` | v19+ | After adopting `@throwOnFieldError` / `@catch`. |
| `fix-all` | v21+ | After each Relay version upgrade; migrates resolver docblocks to `@relayType` / `@relayField`. |
