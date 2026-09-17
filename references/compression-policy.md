# Compression Policy

Context compression is a lossy transform. Treat it like lossy serialization, not neutral paraphrasing.

## Never compress away

Preserve these exactly or structurally:

- numbers, units, ranges, and currencies;
- dates, deadlines, and effective periods;
- negations and prohibitions;
- fact vs assumption status;
- confidence or uncertainty that affects decisions;
- instruction scope and lifecycle state;
- unresolved questions;
- rationale behind material decisions;
- dependencies between assumptions and decisions;
- user corrections to prior state.

## Safe compression order

1. Persist governed state first.
2. Compress raw dialogue second.
3. Validate the summary against governed state.
4. Record what was intentionally omitted if omission can matter later.

## Invariants

A compression is invalid if it changes any of these meanings:

```text
"Assume refund rate = 30% for this model"
        !=
"Refund rate = 30%"
```

```text
"Do not use this framing in the final report"
        !=
"Prefer another framing"
```

```text
"Use 228 for this scenario"
        !=
"Default price is 228"
```

## Summary authority

Derived summaries are caches.

If summary and governed state disagree:

1. prefer the original source when available;
2. otherwise prefer governed state;
3. flag the discrepancy;
4. regenerate the summary if necessary.
