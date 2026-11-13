# Relay Resolvers

Relay Resolvers augment Relay's GraphQL graph with values that are known only on the client. They schematize client state in the same way as server state, and product code uses Relay's familiar data-fetching APIs to access that state. Client state includes data from client-side data stores and derived data that Relay computes from other values in the graph.

Runtime benefits:

- Global memoization with garbage collection
- Efficient reactive recomputation of resolvers
- Efficient UI updates when data changes

Resolvers can model:

- **User-created data**: complex form state, or other data that outlives a specific component tree
- **Client-side database**: persistent data stores like IndexDB, localStorage, or SQLite
- **Third-party APIs**: data that the client fetches directly from a third-party API, for example search results from a third-party search provider
- **Encrypted data**: end-to-end encrypted data that is opaque on the server
- **Legacy data stores**: data from pre-existing data layers, like Redux, so that migrated and un-migrated portions of the app stay in sync
- **Derived data**: fields that are a pure function of other fields (see [Derived Fields](#derived-fields))

## Enabling

The Relay compiler looks at docblocks that include a resolver tag (see the table below for your version) and ignores all other docblocks.

When using Relay Resolvers, the docs recommend configuring a `relayFieldLogger` in your Relay Environment to track errors that resolver functions throw.

```ts
import { Environment, RecordSource, RelayFeatureFlags } from "relay-runtime";
import RelayModernStore from "relay-runtime/lib/store/RelayModernStore";

// It is recommended to log errors thrown by Resolvers
function fieldLogger(event) {
  if(event.kind === "relay_resolver.error") {
    // Log this somewhere!
    console.warn(`Resolver error encountered in ${event.owner}.${event.fieldPath}`)
    console.warn(event.error)
  }
}

const environment = new Environment({
  network: Network.create(/* your fetch function here */),
  store: new RelayModernStore(new RecordSource()),
  relayFieldLogger: fieldLogger
});
```

Resolvers run in the standard `Store` from `relay-runtime` (`RelayModernStore`) in v20.1.1 and v21.0.1. `LiveResolverStore` (`relay-runtime/lib/store/live-resolvers/LiveResolverStore`) re-exports `RelayModernStore` for backward compatibility in both versions; import `Store` in new code. The v20 and v21 docs both describe resolvers as an experimental feature.

### Docblock tags

**The tag depends on the Relay version.** Check `relay-compiler` in `package.json`.

| | Relay v20 | Relay v21 |
| --- | --- | --- |
| Type | `@RelayResolver Todo` | `@relayType Todo` |
| Field | `@RelayResolver Todo.text: String` | `@relayField Todo.text: String` |

The v20 compiler reads a docblock only when it has the `@RelayResolver` tag, and the v21 compiler only when it has `@relayType` or `@relayField`. The examples in this file use the v21 tags. On v20, write `@RelayResolver` in their place; the function, the other tags and the rest of the docblock are the same.

To migrate from v20 to v21, run `relay-compiler codemod fix-all` (v21 only). To keep `@RelayResolver` on v21 during a migration, enable the `allow_legacy_relay_resolver_tag` feature flag in the compiler config.

These tags are the same in v20 and v21:

| Tag | Defines |
| --- | --- |
| `@weak` | A type without an ID. |
| `@rootFragment FragmentName` | The data that a derived field reads. |
| `@live` | A field or strong type whose value changes over time. |
| `@deprecated reason` | A deprecated field. |
| Free text in the docblock | The description of the type or field. |

## Defining Fields

A resolver field is an exported function that accepts an instance of the model type as its first argument and returns the field value. The exported function name must match the field name. A docblock with `@relayField` marks the function. To define a field on a GraphQL model type `TypeName`, add `TypeName`, a dot, and the field definition in GraphQL's schema definition language.

```js
/**
* @relayField TypeName.fieldName(arg1: ArgTypeName): FieldTypeName
*/
```

A simple field:

```tsx
/**
 * @relayField User.name: String
 */
export function name(user: UserModel): string {
  return user.name;
}
```

For a field on a client type, the first argument is the model instance. For a field on a server type, the resolver reads its data through `@rootFragment` (see [Derived Fields](#derived-fields)). Relay efficiently recomputes resolvers when their inputs change, so you do not memoize your resolver function.

The simplest resolver augments an existing type and has no inputs:

```tsx
/**
 * @relayField Query.greeting: String
 */
export function greeting(): string {
  return "Hello World";
}
```

Consuming resolvers is identical to consuming a server field. Product code does not need to know which kind of field it reads.

```tsx
import {useClientQuery, graphql} from 'react-relay';

function Greeting() {
  const data = useClientQuery(graphql`
    query GreetingQuery {
      greeting
    }`, {});
  return <p>{data.greeting}</p>;
}
```

A query that contains only client fields cannot use `usePreloadedQuery` or `useLazyLoadQuery`: both hooks assume they issue a network request, and Flow reports a type error. Use `useClientQuery`. A query that also contains server data uses the standard `useLazyLoadQuery` or `usePreloadedQuery` APIs.

## Defining Client-Only Types

Each client state GraphQL type is backed by a JavaScript object type, its model type. Resolvers on the type receive an instance of the model type as their first argument. A type is strong by default: each instance has an ID that is unique within the type. A weak type has no ID.

### Strong Types with @relayType

Define a strong type with a docblock and an exported function. The function name matches the type name. It accepts an ID as its only argument and returns an instance of the type's model. This function is the model resolver for the type. Resolvers that define edges to this type return the ID of the object.

```tsx
/**
 * @relayType User
 */
export function User(id: DataID): UserModel {
  return UserService.getById(id);
}
```

### Weak Types

If a type has no unique identifier, add the `@weak` docblock tag. A weak type is defined by a docblock followed by an exported type definition that matches the type's name. Resolvers that define edges to weak types return a fully populated model object that matches this type. Weak types create a namespace for a set of fields that belong to a parent object.

```tsx
/**
 * @relayType ProfilePicture
 * @weak
 */
export type ProfilePicture = { url: string, height: number, width: number };
```

### Implementing Interfaces / Unions

Relay Resolver types can implement abstract types that the GraphQL schema defines. The abstract types can come from your GraphQL server schema or from a client schema extension. The same applies to unions.

```tsx
/**
 * @relayType BasicUser implements IUser
 */
export function BasicUser(id: DataID): BasicUserModel {
  return { ...BasicUserService.getById(id), name: 'BasicUser1'};
}
```

## Field Arguments

Define arguments in the field definition of the resolver's docblock. The resolver function reads the arguments as properties on its second argument.

```tsx
/**
 * @relayField User.greet(salutation: String!): String
 */
export function greet(user: UserModel, args: { salutation: string }): string {
  return `${args.salutation}, ${user.name}!`;
}
```

Consuming this field requires passing the argument to the field in the GraphQL query:

```graphql
query MyQuery($salutation: String!) {
  me {
    greet(salutation: $salutation)
  }
}
```

When a derived resolver reads a field that takes arguments, define an explicit fragment argument with `@argumentDefinitions` in the fragment definition. The resolver field then expects this argument as a field argument:

```tsx
/**
 * @relayField User.fancyGreeting: String
 * @rootFragment UserFancyGreetingFragment
 */
export function fancyGreeting(key: UserFancyGreetingFragment$key): string {
  const user = readFragment(graphql`
    fragment UserFancyGreetingFragment on User @argumentDefinitions(
      salutation: {type: "String"},
    ) {
      name
      greet(salutation: $salutation)
    }
  `, key);
  return `${user.name} says ${user.greet}`;
}
```

## Resolver Function Arguments

Relay calls a resolver with these arguments, in this order:

1. The model instance (field on a client type) or the fragment key (field with `@rootFragment`). A field on `Query` without `@rootFragment` has no first argument of this kind.
2. The field arguments object. The slot exists for every resolver; the value is `undefined` when the field declares no arguments.
3. The resolver context (the `resolverContext` value of the `Store`).

```js
import type { LiveState } from 'relay-runtime';

/**
 * @relayField Query.counter: Int
 * @live
 */
export function counter(
  _args,
  context
) {
  return {
    read: () => context.store.getState().counter,
    subscribe: (callback) => {
      return context.store.subscribe(callback);
    },
  };
}
```

Source: `getResolverValue` in `packages/relay-runtime/store/RelayReader.js` (same order in v20.1.1 and v21.0.1). The docs page on context says "third argument" for both cases; the source puts the context right after the arguments slot, so a resolver without a model or fragment receives it second.

## Derived Fields

Derived fields are a pure function of other fields. They exist on any type, server or client. A derived resolver defines a root fragment with the `@rootFragment` docblock tag followed by the name of the fragment. Relay passes the resolver function a fragment key for that fragment. The resolver reads the fragment data with `readFragment` imported from `relay-runtime`.

```tsx
import {readFragment} from 'relay-runtime';

/**
 * @relayField User.fullName: String
 * @rootFragment UserFullNameFragment
 */
export function fullName(key: UserFullNameFragment$key): string {
  const user = readFragment(graphql`
    fragment UserFullNameFragment on User {
        firstName
        lastName
    }
  `, key);
  return `${user.firstName} ${user.lastName}`;
}
```

Relay tracks all the values that the resolver reads from the fragment and recomputes the resolver when any of those values change.

- **Global memoization**: Relay memoizes derived fields. The cache is shared by all components in the application, so 2 sibling components that read the same field trigger 1 computation.
- **Efficient updates**: when a derived resolver recomputes and derives the same value, Relay avoids re-rendering the components that read the field.
- **Composable**: derived fields combine with other derived fields.
- **Discoverable**: values in the graph are discoverable via the GraphQL schema.

`readFragment()` may only be used in Relay Resolvers. It throws an error in any other context.

A derived resolver can read other resolver fields. This composition combines server data, client data and other derived resolvers:

```tsx
/**
 * @relayField CheckoutItem.isValid: Boolean
 * @rootFragment CheckoutItemFragment
 */
export function isValid(key): boolean {
  const item = readFragment(graphql`
    fragment CheckoutItemFragment on CheckoutItem {
      product {
        price
      }
      quantity
    }
  `, key);
  return item.product.price * item.quantity > 0;
}

/**
 * @relayField ShoppingCart.canCheckout: Boolean
 * @rootFragment ShoppingCartFragment
 */
export function canCheckout(key): boolean {
  const cart = readFragment(graphql`
    fragment ShoppingCartFragment on ShoppingCart {
      items {
        isValid
      }
    }
  `, key);
  return cart.items.every(item => item.isValid);
}
```

## Return Types

| Docblock return type | The function returns |
| --- | --- |
| Scalar (`String`, `Int`, `Boolean`) | The JavaScript primitive. |
| List `[T]` | An array of the values that `T` needs. Server types in lists are unsupported. |
| Edge to a strong client type | `{id: DataID}` |
| Edge to a weak client type | An object that matches the weak type's model. |
| Edge to a server type | The `DataID` of the server object. Add `@waterfall` where you read the field. |
| Abstract type with strong members | `{id: DataID, __typename: string}` |
| Abstract type with weak members | `{__relay_model_instance: T, __typename: string}` |
| `RelayResolverValue` | Any immutable JavaScript value. |

Relay emits type assertions in the generated code. They flag a resolver whose return value does not match its docblock.

### Scalars

```tsx
/**
 * @relayField Post.isValid: Boolean
 */
export function isValid(post: PostModel): boolean {
  return post.content !== "" && post.author != null;
}
```

### Lists

A resolver can return a list of the corresponding type. Any supported return type can be wrapped in a list, except server types:

```tsx
/**
 * @relayField User.favoriteColors: [String]
 */
export function favoriteColors(user: UserModel): string[] {
  return user.favoriteColors;
}
```

### Edges to Strong Client Types

Return `{ id: DataID }`. Relay invokes the model resolver function of the type:

```tsx
import {DataID} from 'relay-runtime';
/**
 * @relayField Post.author: User
 */
export function author(post: PostModel): { id: DataID } {
  return { id: post.authorId };
}
```

### Edges to Weak Types

Return an object that matches the model type of the weak type:

```tsx
/**
 * @relayField User.profilePicture: ProfilePicture
 */
export function profilePicture(user: UserModel): ProfilePicture {
  return {
    url: user.profilePicture.url,
    width: user.profilePicture.width,
    height: user.profilePicture.width,
  }
}
```

### Edges to Server Types (@waterfall)

Resolvers can model edges to types that the server schema defines and that implement the `Node` specification. Each object that implements `Node` has a globally unique ID, so the resolver returns that ID. At compile time, Relay derives a GraphQL query for each selection on this field and lazily fetches that data on render.

```tsx
import {DataID} from 'relay-runtime';
/**
 * @relayField Post.author: User
 */
export function author(post: PostModel): DataID {
  return post.authorId;
}
```

Edges to server types that only the client knows force Relay to fetch data lazily. This forces an additional cascading network roundtrip, which is generally not optimal. At compile time, Relay requires the selection that reads a client-to-server edge field to carry the `@waterfall` directive:

```tsx
function Post() {
  const data = useLazyLoadQuery(graphql`
    query PostQuery {
      post {
        author @waterfall {
          name
        }
      }
    }`, {});
  return <p>{data.post.author.name}</p>;
}
```

### Abstract Types (interfaces and unions)

A resolver can return some permutations of abstract types (GraphQL unions and interfaces). Use the abstract type's name in the docblock field description and include the typename in the returned object. The object shape depends on the members:

- Strong members: `{id: DataID, __typename: string}`.
- Weak members: `{__relay_model_instance: T, __typename: string}`.

```tsx
import {DataID} from 'relay-runtime';

type AnimalTypenames = "Cat" | "Dog";
/**
 * @relayField User.pet: Animal
 */
export function pet(user: User): {id: DataID, __typename: AnimalTypenames } {
  return {id: "5", __typename: "Dog" }
}
```

Relay does not support these combinations:

- Unions that include weak types.
- Abstract types that mix strong and weak members.
- Abstract types that include server-backed members.

Resolvers cannot define the abstract types themselves. Define interfaces, unions and their members in a client schema extension:

```graphql title="client-schema.graphql"
interface Animal {
 legs: Int
}

extend type Cat implements Animal {
  __do_not_use: String # Placeholder because GraphQL does not allow empty field sets.
}
```

### RelayResolverValue Escape Hatch

For an arbitrary JavaScript value that has no corresponding GraphQL type, the custom return type `RelayResolverValue` returns any JavaScript value from the resolver. JavaScript values that resolvers return should be immutable.

```tsx
/**
 * @relayField Post.publishDate: RelayResolverValue
 */
export function metadata(post: PostModel): Date {
  return post.publishDate;
}
```

Consumers see a TypeScript or Flow type derived from the function's return type. The docs call `RelayResolverValue` an escape hatch that a future Relay version may deprecate. The preferred pattern is a custom scalar in the client schema extensions plus a type definition for that scalar in the Relay config.

## Live Resolvers

Relay Resolvers support the `@live` docblock tag. Live resolvers return a `LiveState` shaped object. Relay calls its `read()` method to get the current value, and its `subscribe()` method to learn of changes to the value. When the value changes, Relay recomputes the derived fields that depend on the field, including transitive dependencies, and updates the components that read changed fields.

Both field resolvers and strong model resolvers may carry `@live`. `@live` on a type works on v20 and v21.

A `LiveState` is conceptually similar to an observable or a signal. When a `LiveState` notifies its subscriber of an update, the notification does not include the new value. Relay calls `read()` to get the new value. Over-notification, where the read value has not changed, is supported. For performance, the provider of the `LiveState` value confirms that the value changed before it notifies Relay.

### Redux bridge example

A helper function can read a reactive data store and return a `LiveState` object. For a Redux store, a wrapper can expose a `LiveState` for a given selector:

```ts
type Selector<T> = (state: State) => T;

function selectorAsLiveState<T>(selector: Selector<T>): LiveState<T> {
  let currentValue = selector(store.getState());
  return {
    read: () => currentValue,
    subscribe: (cb) => {
      return store.subscribe(() => {
        const newValue = selector(store.getState());
        if (newValue === currentValue) {
          return;
        }
        currentValue = newValue;
        cb();
      });
    },
  };
}
```

A live resolver that uses this helper:

```tsx
/**
 * @relayField Query.counter: Int
 * @live
 */
export function counter(): LiveState<number> {
  return selectorAsLiveState(getCounter);
}

function getCounter(state) {
  return state.counter;
}
```

### Batching live updates

One change in the data layer can notify many `@live` resolver subscriptions. By default each update makes Relay determine which components to update, which can duplicate work. Batch updates to `@live` resolvers by wrapping the state updates in a `batchLiveStateUpdates()` call on your `RelayStore` instance:

```ts
const store = createStore(reducer);
const originalDispatch = store.dispatch;

function wrapped(action) {
  relayStore.batchLiveStateUpdates(() => {
    originalDispatch(action);
  })
}

store.dispatch = wrapped;
```

## Suspense

If a live resolver is in a loading state, it can return the suspense sentinel value. All consumers of that field suspend until the field updates with a non-suspense value. A query or fragment suspends if it reads any resolver field in a suspended state, even if it reads that field indirectly via another resolver's `@rootFragment`.

```ts
import {suspenseSentinel} from 'relay-runtime';

/**
 * @relayField Query.myIp: String
 * @live
 */
export function myIp(): LiveState<string> {
  return {
    read: () => {
      const state = store.getState();
      const ipLoadObject = state.ip;
      if (ipLoadObject.status === "LOADING") {
        return suspenseSentinel();
      }
      return state.ip;
    },
    subscribe: (cb) => {
      return store.subscribe(cb);
    },
  };
}
```

## Error Handling

If a resolver throws an error, Relay logs the error to the environment's user-provided `relayFieldLogger` and returns `null` for the field that the resolver defines. Resolver fields therefore cannot be typed non-null in the schema: the compiler does not allow it.

```ts
function fieldLogger(event) {
  if(event.kind === "relay_resolver.error") {
    // Log this somewhere!
    console.warn(`Resolver error encountered in ${event.owner}.${event.fieldPath}`)
    console.warn(event.error)
  }
}

const environment = new Environment({
  network: Network.create(/* your fetch function here */),
  store: new RelayModernStore(new RecordSource()),
  relayFieldLogger: fieldLogger
});
```

### Logger event shape

The `relayFieldLogger` receives this event for a thrown resolver error. The `errors` docs list the first 4 fields. The `relayFieldLogger` docs add `shouldThrow` and `handled`.

```ts
export type RelayResolverErrorEvent = {
  +kind: 'relay_resolver.error',
  +owner: string,
  +fieldPath: string,
  +error: Error,
  +shouldThrow: boolean,
  +handled: boolean,
};
```

A live resolver can throw when Relay first evaluates it and when Relay calls `read()`. Relay handles both cases the same way. When the reading operation carries `@throwOnFieldError`, the read also throws after the logger runs.

### @semanticNonNull

Relay resolver fields can be semantically non-null, like server schema fields. Add `@semanticNonNull` to the docblock of a resolver to mark the field as non-nullable in the semantic sense, while the client still handles errors:

```ts
/**
 * @relayField RelayExample.semantic_non_null_field: String @semanticNonNull
 */
export function semantic_non_null_field(
  model: RelayExampleModel,
): string {
  return model.someField ?? 'field was null, this is the default';
}
```

## Deprecation and Descriptions

Add `@deprecated` with an optional reason to mark a field deprecated. Add free text to the docblock to describe a type or a field. Both are markdown. The Relay VS Code extension shows descriptions on hover and in autocomplete, and shows deprecated fields greyed out and struck through, with the reason.

```tsx
/**
 * @relayField Author.fullName: String
 *
 * @deprecated Google "Falsehoods Programmers Believe About Names"
 */
export function fullName(author: AuthorModel): string {
  return `${author.firstName} ${author.lastName}`;
}
```

```tsx
/**
 * @relayField Author.fullName: String
 *
 * The author's first and last name. Does not include
 * any [honorifics](https://en.wikipedia.org/wiki/Honorific).
 */
export function fullName(author: AuthorModel): string {
  return `${author.firstName} ${author.lastName}`;
}
```

Descriptions on a type go in the `@relayType` docblock in the same way.

## Limitations

- **No `info` argument**: standard GraphQL resolvers receive an `info` argument; Relay Resolvers do not.
- **Schema constructs**: input types, enums, and interfaces cannot be defined by resolvers (though resolver types can implement schema interfaces).
- **No mutations**: resolvers support only the read path.
- **Lazy per-fragment evaluation**: resolvers are always evaluated lazily on a per-fragment basis. A resolver that is not read is never evaluated. If the client schema makes async requests as it reads data, waterfalls can occur.
- **Nullable return types**: the compiler does not allow non-nullable resolver fields, because a resolver that throws makes the field null. Use `@semanticNonNull` for logically required fields.
- **Docblock verbosity**: the docblock duplicates information that the function name and types already specify. Relay emits type assertions in its generated types to enforce that these values match.
- **Context is store-wide**: pass `resolverContext` to the initialization of `RelayModernStore`: `new RelayModernStore(source, { resolverContext: { store: customStore } })`. Each resolver receives that value as its last argument. Set `resolverContextType` in the project config to type-check it.
- **Waterfalls through `@waterfall`**: edges into server types trigger an extra network roundtrip.
