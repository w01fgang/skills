# Relay Resolvers

Relay Resolvers extend the GraphQL graph with values known only to the client. They let you model derived state, client-only data, third-party API results, and legacy stores (Redux, IndexedDB, localStorage) as fields on your GraphQL schema — consumed by the same hooks (`useFragment`, `useClientQuery`, `usePreloadedQuery`) as server data.

Runtime benefits:

- Global memoization with garbage collection
- Efficient reactive recomputation on input change
- Fine-grained re-renders — only components reading a changed field update

Use resolvers when state is:

- Derived from other GraphQL fields (`fullName` from `firstName`/`lastName`)
- Client-only (form state, selection, IndexedDB rows)
- Fetched outside Relay (third-party search, end-to-end encrypted blobs)
- Bridging legacy stores during migration

## Enabling

Add resolver support to `relay.config.json` (the "Enabling" page in the docs returns 404 at time of writing; these flags come from the Relay compiler source and examples in adjacent pages):

```json
{
  "src": "./src",
  "language": "typescript",
  "schema": "./schema.graphql",
  "schemaExtensions": ["./src/schema-extensions"],
  "featureFlags": {
    "enable_relay_resolver_transform": true,
    "enable_resolver_normalization_ast": true
  }
}
```

Then run the compiler (`relay-compiler`) — it parses `@RelayResolver` docblocks and generates artifacts alongside your fragments.

## Defining Fields on Server Types

A resolver is a named exported function plus a docblock. The function name **must** match the field name.

```tsx
// UserGreetingResolver.ts
import type { UserModel } from "./UserModel";

/**
 * @RelayResolver User.greeting: String
 */
export function greeting(user: UserModel): string {
  return `Hello, ${user.name}!`;
}
```

The first argument is the model instance (for server types, Relay passes the record). Relay memoizes automatically — no `useMemo` needed.

Consume it like any field:

```tsx
import { graphql, useFragment } from "react-relay";
import type { UserGreeting$key } from "./__generated__/UserGreeting.graphql";

function UserGreeting({ user }: { user: UserGreeting$key }) {
  const data = useFragment(
    graphql`
      fragment UserGreeting on User {
        greeting
      }
    `,
    user,
  );
  return <h1>{data.greeting}</h1>;
}
```

## Defining Client-Only Types

A client type is backed by a JavaScript model object. Two flavors: **strong** (has an ID, memoized) and **weak** (no ID, inline).

### Strong Types with @RelayResolver

Strong types have unique IDs. Define with a capitalized function matching the type name:

```tsx
// TodoModel.ts
import type { DataID } from "relay-runtime";
import { TodoService } from "./TodoService";

export type TodoModel = {
  id: DataID;
  text: string;
  completed: boolean;
};

/**
 * @RelayResolver Todo
 */
export function Todo(id: DataID): TodoModel {
  return TodoService.getById(id);
}

/**
 * @RelayResolver Todo.text: String
 */
export function text(todo: TodoModel): string {
  return todo.text;
}

/**
 * @RelayResolver Todo.completed: Boolean
 */
export function completed(todo: TodoModel): boolean {
  return todo.completed;
}
```

### @RelayResolverModel Shorthand

`@RelayResolverModel` generates the model resolver from a class or object type automatically — use it when your model already has the right shape:

```tsx
/**
 * @RelayResolver
 * @RelayResolverModel
 */
export class Todo {
  id: DataID;
  text: string;
  completed: boolean;

  constructor(id: DataID, text: string) {
    this.id = id;
    this.text = text;
    this.completed = false;
  }
}
```

Fields on `Todo` can then be defined as methods or separate resolvers.

### Weak Types

Weak types have no independent identity — they're bags of fields owned by a parent. Mark with `@weak`:

```tsx
/**
 * @RelayResolver ProfilePicture
 * @weak
 */
export type ProfilePicture = {
  url: string;
  width: number;
  height: number;
};

/**
 * @RelayResolver User.profilePicture: ProfilePicture
 */
export function profilePicture(user: UserModel): ProfilePicture {
  return {
    url: user.pic.url,
    width: user.pic.width,
    height: user.pic.height,
  };
}
```

### Implementing Interfaces / Unions

Resolver types can implement schema interfaces or participate in unions:

```tsx
/**
 * @RelayResolver BasicUser implements IUser
 */
export function BasicUser(id: DataID): BasicUserModel {
  return { ...BasicUserService.getById(id), name: "Basic" };
}
```

Include `__typename` when returning union members:

```tsx
/**
 * @RelayResolver User.pet: Animal
 */
export function pet(
  user: UserModel,
): { id: DataID; __typename: "Dog" | "Cat" } {
  return { id: user.petId, __typename: user.petKind };
}
```

## Field Arguments

Declare arguments in the docblock; they arrive as the second function argument.

```tsx
/**
 * @RelayResolver User.greet(salutation: String!): String
 */
export function greet(
  user: UserModel,
  args: { salutation: string },
): string {
  return `${args.salutation}, ${user.name}!`;
}
```

Query usage:

```graphql
query GreetQuery($salutation: String!) {
  me {
    greet(salutation: $salutation)
  }
}
```

When a derived resolver reads a field that takes arguments, thread them through `@argumentDefinitions`:

```tsx
/**
 * @RelayResolver User.fancyGreeting: String
 * @rootFragment UserFancyGreetingFragment
 */
export function fancyGreeting(
  key: UserFancyGreetingFragment$key,
): string {
  const user = readFragment(
    graphql`
      fragment UserFancyGreetingFragment on User
      @argumentDefinitions(salutation: { type: "String!" }) {
        name
        greet(salutation: $salutation)
      }
    `,
    key,
  );
  return `${user.name}: ${user.greet}`;
}
```

## Derived Fields

Derived resolvers are pure functions of other GraphQL fields. They use `@rootFragment` + `readFragment` from `relay-runtime`. Relay tracks the fragment's dependencies and recomputes only when those change — cheaper than a React `useMemo` because the result is shared across all components.

```tsx
import { readFragment, graphql } from "relay-runtime";
import type { UserFullNameFragment$key } from "./__generated__/UserFullNameFragment.graphql";

/**
 * @RelayResolver User.fullName: String
 * @rootFragment UserFullNameFragment
 */
export function fullName(key: UserFullNameFragment$key): string {
  const user = readFragment(
    graphql`
      fragment UserFullNameFragment on User {
        firstName
        lastName
      }
    `,
    key,
  );
  return `${user.firstName} ${user.lastName}`;
}
```

Derived resolvers compose — they can read other resolvers:

```tsx
/**
 * @RelayResolver CheckoutItem.isValid: Boolean
 * @rootFragment CheckoutItemFragment
 */
export function isValid(key: CheckoutItemFragment$key): boolean {
  const item = readFragment(
    graphql`
      fragment CheckoutItemFragment on CheckoutItem {
        product {
          price
        }
        quantity
      }
    `,
    key,
  );
  return item.product.price * item.quantity > 0;
}

/**
 * @RelayResolver ShoppingCart.canCheckout: Boolean
 * @rootFragment ShoppingCartFragment
 */
export function canCheckout(key: ShoppingCartFragment$key): boolean {
  const cart = readFragment(
    graphql`
      fragment ShoppingCartFragment on ShoppingCart {
        items {
          isValid
        }
      }
    `,
    key,
  );
  return cart.items.every((i) => i.isValid);
}
```

## Return Types

### Scalars

```tsx
/** @RelayResolver Post.isValid: Boolean */
export function isValid(post: PostModel): boolean {
  return post.content !== "" && post.author != null;
}
```

### Lists

Any supported return type can be wrapped in a list (except raw server types):

```tsx
/** @RelayResolver User.favoriteColors: [String] */
export function favoriteColors(user: UserModel): string[] {
  return user.favoriteColors;
}
```

### Edges to Strong Client Types

Return `{ id: DataID }` — Relay invokes the type's model resolver to hydrate fields:

```tsx
/** @RelayResolver Post.author: User */
export function author(post: PostModel): { id: DataID } {
  return { id: post.authorId };
}
```

### Edges to Weak Types

Return the full object:

```tsx
/** @RelayResolver Post.cover: CoverImage */
export function cover(post: PostModel): CoverImage {
  return { url: post.coverUrl, alt: post.coverAlt };
}
```

### Edges to Server Types (@waterfall)

A resolver can point into the server graph by returning a `DataID`. Consumers must annotate the selection with `@waterfall` to acknowledge the extra round trip:

```tsx
/** @RelayResolver Post.author: ServerUser */
export function author(post: PostModel): DataID {
  return post.authorId;
}
```

```graphql
query PostAuthorQuery($id: ID!) {
  post(id: $id) {
    author @waterfall {
      name
      avatarUrl
    }
  }
}
```

### RelayResolverValue Escape Hatch

For arbitrary JS values that shouldn't be in the GraphQL schema (Dates, class instances), use `RelayResolverValue`. Keep the value immutable:

```tsx
/** @RelayResolver Post.publishDate: RelayResolverValue */
export function publishDate(post: PostModel): Date {
  return new Date(post.publishTimestamp);
}
```

## Live Resolvers

Live resolvers push updates into the Relay store. Add `@live` and return a `LiveState<T>`:

```tsx
export type LiveState<T> = {
  read(): T;
  subscribe(cb: () => void): () => void; // returns unsubscribe
};
```

`subscribe` receives only a notification — Relay calls `read()` itself when told the value changed.

### Redux bridge example

```tsx
import type { LiveState } from "relay-runtime";
import { store, type AppState } from "./reduxStore";

type Selector<T> = (s: AppState) => T;

function selectorAsLiveState<T>(selector: Selector<T>): LiveState<T> {
  let current = selector(store.getState());
  return {
    read: () => current,
    subscribe: (cb) =>
      store.subscribe(() => {
        const next = selector(store.getState());
        if (next === current) return;
        current = next;
        cb();
      }),
  };
}

/**
 * @RelayResolver Query.counter: Int
 * @live
 */
export function counter(): LiveState<number> {
  return selectorAsLiveState((s) => s.counter);
}
```

Consume in a component:

```tsx
import { graphql, useClientQuery } from "react-relay";

function Counter() {
  const data = useClientQuery(
    graphql`
      query CounterQuery {
        counter
      }
    `,
    {},
  );
  return <span>{data.counter}</span>;
}
```

### Batching live updates

When one action mutates many slices, wrap dispatch so Relay coalesces recomputation:

```tsx
const originalDispatch = store.dispatch;
store.dispatch = (action) => {
  relayEnvironment.getStore().batchLiveStateUpdates(() => {
    originalDispatch(action);
  });
};
```

## Suspense

A live resolver can suspend by returning the suspense sentinel from `read`. All consumers of that field (and anything transitively depending on it, even through a derived resolver's `@rootFragment`) suspend until the sentinel is replaced.

```tsx
import { suspenseSentinel, type LiveState } from "relay-runtime";

/**
 * @RelayResolver Query.myIp: String
 * @live
 */
export function myIp(): LiveState<string> {
  return {
    read: () => {
      const s = ipStore.getState();
      if (s.status === "LOADING") return suspenseSentinel();
      if (s.status === "READY") return s.value;
      throw new Error("IP fetch failed");
    },
    subscribe: (cb) => ipStore.subscribe(cb),
  };
}
```

Wrap consumers in `<Suspense>`:

```tsx
function App() {
  return (
    <Suspense fallback={<Spinner />}>
      <MyIpView />
    </Suspense>
  );
}
```

## Error Handling

If a resolver throws, Relay:

1. Reports to the environment's `relayFieldLogger`
2. Returns `null` for that field

Resolver fields therefore **cannot be typed non-null** in the schema — the compiler rejects it.

```tsx
import { Environment, Network, RecordSource, Store } from "relay-runtime";

function fieldLogger(event: {
  kind: string;
  owner: string;
  fieldPath: string;
  error?: Error;
}) {
  if (event.kind === "relay_resolver.error") {
    console.warn(`Resolver error in ${event.owner}.${event.fieldPath}`);
    console.warn(event.error);
  }
}

const environment = new Environment({
  network: Network.create(fetchFn),
  store: new Store(new RecordSource()),
  relayFieldLogger: fieldLogger,
});
```

### @semanticNonNull

When a field is *logically* required but must still be nullable for the error model, use `@semanticNonNull`. Clients can treat it as non-null in product code while Relay retains the right to null it on error:

```tsx
/**
 * @RelayResolver User.email: String @semanticNonNull
 */
export function email(user: UserModel): string {
  return user.email ?? "unknown@example.com";
}
```

### Handling expected errors

For predictable fallbacks, return a default value instead of throwing:

```tsx
/**
 * @RelayResolver User.avatarUrl: String
 */
export function avatarUrl(user: UserModel): string {
  try {
    return buildAvatarUrl(user);
  } catch {
    return "/default-avatar.png";
  }
}
```

## Limitations

- **No `info` argument** — standard GraphQL resolvers receive a context/info object; Relay Resolvers do not.
- **Schema constructs** — input types, enums, and interfaces cannot be defined *by* resolvers (though resolver types can implement schema interfaces).
- **No mutations** — reactive mutation semantics are still being designed. Mutate underlying stores directly; live resolvers propagate the change.
- **Lazy per-fragment evaluation** — resolvers run on read, not eagerly. If the implementation requires async work (e.g., a fetch inside `read`), you'll need a live resolver + suspense sentinel; there's no built-in async resolver.
- **Non-null return types forbidden** — every resolver field is nullable in the generated schema to accommodate thrown errors. Use `@semanticNonNull` for logically-required fields.
- **Docblock verbosity** — type information is duplicated between the docblock GraphQL signature and the TypeScript function. Grats-inspired inference is on the roadmap.
- **No resolver context** — there's no per-request context object; resolvers close over module-scope singletons (stores, services).
- **Waterfalls through `@waterfall`** — edges into server types trigger extra round trips; the directive makes this explicit but doesn't eliminate the cost.

## Decision Table

| Need                                                              | Use                        | Why                                                                           |
| ----------------------------------------------------------------- | -------------------------- | ----------------------------------------------------------------------------- |
| Value derived from other GraphQL fields, shared across components | **Resolver (derived)**     | Global memoization, exposed in schema, auto-recomputes on dep change          |
| Client-only entity with ID (todo, draft, selection set)           | **Resolver (strong type)** | Integrates with Relay store, fragments, pagination                            |
| Reactive value from Redux / Zustand / Jotai / external store      | **Live resolver**          | `LiveState` bridges external pub/sub into Relay's reactive graph              |
| Value fetched async from third-party API                          | **Live resolver + suspense sentinel** | Resolver can suspend consumers while loading                       |
| Local UI state (open/closed, hover, input draft) scoped to one component | **`useState`**      | No need for graph membership; simpler, no compiler step                       |
| State shared across a subtree but not the whole app               | **React Context**          | Cheaper than a resolver, avoids schema churn, fine for non-GraphQL concerns   |
| Authoritative data owned by the server                            | **Server field**           | Single source of truth, supports mutations, network caching, normalization    |
| Legacy store you're migrating to GraphQL                          | **Live resolver (bridge)** | Lets product code target the final schema while data still lives in Redux/etc |
| One-off computation inside a single component                     | **`useMemo`**              | Resolver overhead not justified if not shared                                 |
| Mutable collection with complex writes                            | **Server field + mutation** | Resolvers don't support mutations; keep writes on the server                  |
