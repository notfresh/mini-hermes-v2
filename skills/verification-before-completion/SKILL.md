---
name: verification-before-completion
description: Use when finishing any task or before declaring work complete - ensures work is actually verified, not just assumed done
---

# Verification Before Completion

## Overview

**"Done" means verified, not "it should work".** The gap between "I think this works" and "this demonstrably works" is where bugs hide. Close it before declaring completion.

## The Iron Law

```
NEVER SAY "DONE" UNTIL YOU HAVE VERIFIED IT
```

## The Gate Function

Before declaring any task complete, run the verification gate:

1. **What did I change?** — enumerate files, code, config touched
2. **How do I prove it works?** — what test, command, or check exercises the change?
3. **Did I run it?** — actually execute the verification, don't reason about it
4. **What could still be wrong?** — edge cases, error paths, related code

If any step has no answer, the task is NOT done.

## Common Failures

- "It compiles, so it works" — Compilation is not behavior
- "I tested the happy path" — Error paths are where bugs live
- "The logic is simple, I don't need to test" — Simplicity is exactly when verification is skipped
- "I verified it before" — Verify again after any change; state drifts

## Red Flags - STOP

| Thought | Reality |
|---------|---------|
| "It should work" | Should ≠ verified. Run it. |
| "I don't have time to test" | You don't have time to debug it twice. |
| "It worked for me once" | One data point is not verification. |
| "Trust me, it's fine" | Trust is not evidence. |

## Verification Toolkit (pick what fits)

- Run the actual command / program and check output
- Run a test suite or write a quick regression check
- Read the code once more with "what could break?" eyes
- Ask: "what would make this fail?" and test that too

## The Bottom Line

Verification is the difference between delivering work and delivering a problem. If you cannot demonstrate it works, it is not done — regardless of how confident you are.
