// Compile-time-only helpers used by types/note.ts and types/auth.ts to
// pin every generated-schema alias (see api/generated/schema.ts) to its
// expected field set.
//
// Without this, a hand-written alias pointed at the wrong (but
// structurally compatible) schema key -- e.g. `ApiTokenMeta` aliased to
// `CreateApiTokenResponse`'s key, a strict superset with an extra
// `token` field -- passes silently: `make check-api-types` only diffs
// the *generated* file, never these hand-written re-exports, and
// TypeScript's structural typing accepts a superset value wherever a
// subset shape is expected. `Expect<EqualKeys<...>>` below fails `tsc`
// instead, catching the exact class of drift this migration exists to
// prevent (found in code review, see the adjacent pins for the reasoning
// each one exists to guard).
//
// `never` is assignable to every type, including a `true`-constrained
// generic parameter -- so a naive "does this reduce to `never` on
// mismatch" check would silently pass. `EqualKeys` deliberately resolves
// a mismatch to a descriptive object type instead of `never`, so
// `Expect<...>` actually rejects it.
export type Expect<T extends true> = T;

export type EqualKeys<T, Keys extends string> = keyof T extends Keys
  ? Keys extends keyof T
    ? true
    : {
        pinMismatch: "alias is missing expected field(s)";
        expected: Keys;
        actual: keyof T;
      }
  : { pinMismatch: "alias has unexpected field(s)"; expected: Keys; actual: keyof T };
