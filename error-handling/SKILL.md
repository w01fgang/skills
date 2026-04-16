---
name: error-handling
description: Use when writing async operations, API calls, database operations, or external service integrations — enforces the no-throw pattern with `@power-rent/try-catch` instead of traditional try/catch blocks with manual Sentry reporting.
---

# Error Handling

## Overview

Prefer the **no-throw pattern** over traditional try/catch for async operations. The `@power-rent/try-catch` package makes error handling explicit: handle recoverable failures locally, report when developers need visibility, and only throw on unrecoverable paths.

## When to Use

- API calls and external service integrations
- Database operations that may fail
- Any async operation where you want automatic Sentry reporting
- Functions requiring explicit, typed error handling

**Use traditional try/catch only when:**
- Catching and re-throwing with additional context
- Simple synchronous code that doesn't need Sentry
- The operation is trivial and monitoring is unnecessary

## Core Pattern

```typescript
import Try from '@power-rent/try-catch/nextjs';

// Recoverable error: inspect the error and respond gracefully without reporting
const error = await new Try(riskyOperation, arg1, arg2)
  .error();

if (error) {
  return { success: false, error };
}

// Expected failure: keep the app moving with a default value
const result = await new Try(fetchData, userId)
  .default(null)
  .value();

// Unrecoverable failure: report with context, then throw
const data = await new Try(apiCall, params)
  .report('API call failed')
  .breadcrumbs(['userId', 'action'])
  .tags({ service: 'external-api' })
  .debug(isDevelopment)
  .unwrap();
```

## Quick Reference

| Method | Returns | Pattern |
|--------|---------|---------|
| `.error()` | `Error \| void` | No-throw — inspect and handle locally |
| `.value()` | `T \| void \| default` | No-throw — use value or fallback |
| `.result()` | `{ success, value \| error }` | Discriminated union — branch explicitly |
| `.unwrap()` | `T` or throws | Traditional — use sparingly |

| Config | Purpose |
|--------|---------|
| `.report(msg)` | Sentry error message |
| `.breadcrumbs(keys)` | Debug breadcrumbs |
| `.tags({ k: v })` | Sentry tags |
| `.debug(bool)` | Console logging |
| `.default(val)` | Fallback value |
| `.finally(fn)` | Cleanup callback |

## Breadcrumb Patterns

Use the breadcrumb form that matches the wrapped function signature:

```typescript
import Try from '@power-rent/try-catch/nextjs';

// 1. First argument is an object: extract keys directly
await new Try(updateUser, { userId, action, email })
  .breadcrumbs(['userId', 'action'])
  .report('Failed to update user')
  .value();

// 2. Variadic transformers: works with any parameter types
await new Try(processOrder, orderId, amount, urgent)
  .breadcrumbs(
    (id: string) => ({ orderId: id }),
    (price: number) => ({ priceBucket: price > 100 ? 'high' : 'low' }),
    (isUrgent: boolean) => ({ priority: isUrgent ? 'urgent' : 'normal' })
  )
  .report('Failed to process order')
  .value();

// 3. Positional array syntax: mix direct values and object key extraction
await new Try(syncVehicle, vehicleId, { tenantId, locationId }, retryCount)
  .breadcrumbs([
    'vehicleId',
    ['tenantId', 'locationId'],
    'retryCount',
  ])
  .report('Failed to sync vehicle')
  .value();

// 4. Indexed object syntax: target specific parameter positions
await new Try(callApi, endpoint, payload, headers)
  .breadcrumbs({
    0: (url: string) => ({ endpoint: url }),
    1: ['userId', 'action'],
    2: (requestHeaders: Record<string, string>) => ({
      headerCount: Object.keys(requestHeaders).length,
    }),
  })
  .report('API call failed')
  .value();
```

## Migration Guide

When converting from traditional try/catch, preserve the intent, not necessarily the exact return shape:

```typescript
// Before: try/catch with manual reporting
try {
  const data = await apiCall(params);
  return { success: true, data };
} catch (error) {
  Sentry.captureException(error, { tags: { operation: 'apiCall' } });
  return { success: false, error };
}

// After: no-throw pattern with the same public contract
const attempt = new Try(apiCall, params)
  .report('API call failed')
  .tag('operation', 'apiCall');

await attempt.value(); // triggers reporting on failure
const outcome = await attempt.result();

if (!outcome.success) {
  return { success: false, error: outcome.error };
}

return { success: true, data: outcome.value };
```

## Handling Specific Error Types

For typed error handling:

```typescript
import Try from '@power-rent/try-catch/nextjs';

// Custom error classes
class NetworkError extends Error {}
class ValidationError extends Error {}

// Handle network timeouts
const error = await new Try(fetchWithTimeout, url, 5000)
  .error();

if (error instanceof NetworkError) {
  return { success: false, error: 'Network unavailable' };
}

// Handle validation errors
const result = await new Try(validateUserInput, input)
  .default({ valid: false, errors: [] })
  .value();

if (result && !result.valid) {
  return { success: false, error: result.errors };
}
```

## Common Mistakes

```typescript
// ❌ Avoid: manual Sentry + try/catch for async ops
try {
  const result = await riskyOperation();
} catch (error) {
  Sentry.captureException(error);
  console.error(error);
}

// ✅ Use Try instead
const error = await new Try(riskyOperation)
  .error();

// ❌ Avoid: nested try/catch without context
try {
  try {
    await nestedOperation();
  } catch (innerError) {
    throw new Error('Wrapped: ' + innerError.message);
  }
} catch (error) {
  Sentry.captureException(error);
}

// ✅ Use Try with breadcrumbs for context
const result = await new Try(nestedOperation, { parentOperation, childOperation })
  .report('Nested operation failed')
  .breadcrumbs(['parentOperation', 'childOperation'])
  .value();

// ❌ Avoid: missing error context in reports
const result = await new Try(operation)
  .report('Something failed')  // Too vague
  .value();

// ✅ Include specific context
const result = await new Try(operation, userId, action)
  .report(`Failed to ${action} for user ${userId}`)
  .breadcrumbs(
    (id: string) => ({ userId: id }),
    (currentAction: string) => ({ action: currentAction })
  )
  .value();
```

## Testing Error Scenarios

When testing error handling:

```typescript
// Mock failures in tests
const mockApiCall = vi.fn().mockRejectedValue(new Error('API down'));

it('handles API failures gracefully', async () => {
  const error = await new Try(mockApiCall)
    .error();

  expect(error).toBeDefined();
  expect(error.message).toBe('API down');
});

// Test with custom error types
const mockValidation = vi.fn().mockRejectedValue(new ValidationError('Invalid input'));

it('handles validation errors', async () => {
  const result = await new Try(mockValidation)
    .report('Validation failed')
    .default({ valid: false })
    .value();

  expect(result.valid).toBe(false);
});
```
