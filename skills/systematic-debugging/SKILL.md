---
name: systematic-debugging
description: Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes
---

# Systematic Debugging

## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** ALWAYS find root cause before attempting fixes. Symptom fixes are failure.

**Violating the letter of this process is violating the spirit of debugging.**

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven't completed Phase 1, you cannot propose fixes.

## When to Use

Use for ANY technical issue:
- Test failures
- Bugs in production
- Unexpected behavior
- Build failures

**Use this ESPECIALLY when:**
- Under time pressure (emergencies make guessing tempting)
- "Just one quick fix" seems obvious
- You've already tried multiple fixes
- You don't fully understand the issue

## The Four Phases

You MUST complete each phase before proceeding to the next.

### Phase 1: Root Cause Investigation

**BEFORE attempting ANY fix:**

1. **Read Error Messages Carefully**
   - Don't skip past errors or warnings
   - Read stack traces completely
   - Note line numbers, file paths, error codes

2. **Reproduce Consistently**
   - Find a reliable way to trigger the bug
   - Note exact steps and inputs
   - If you can't reproduce it, you can't fix it

3. **Collect Evidence**
   - Error messages, logs, output, state
   - What changed recently? (code, config, environment)

### Phase 2: Pattern Analysis

- Identify the type of bug: logic error, off-by-one, race condition, resource leak, config issue
- Look for related issues in the same area
- Form a clear mental model of what SHOULD happen vs what IS happening

### Phase 3: Hypothesis and Testing

- Form a hypothesis: "The bug is caused by X because Y"
- Test it with the smallest possible experiment (add logging, inspect state, minimal repro)
- If the hypothesis is wrong, return to Phase 1 with new evidence

### Phase 4: Implementation

- Fix the ROOT CAUSE, not the symptom
- Write a regression test that would have caught this bug
- Verify the fix actually resolves the original symptom
- Confirm no new issues introduced

## Red Flags - STOP and Follow Process

| Thought | Reality |
|---------|---------|
| "Let me try this fix and see" | That's guessing, not debugging. Find root cause first. |
| "I know what's wrong" | Without investigation, you know nothing. |
| "It worked before, must be X" | Verify, don't assume. |
| "Just a quick patch" | Quick patches mask underlying issues. |
| "I can't reproduce it but let me fix it anyway" | You can't fix what you can't reproduce. |

## Common Rationalizations

- "Under time pressure, I need to fix it NOW" — Systematic is faster than thrashing.
- "It's a simple bug" — Simple bugs have root causes too.
- "I've already tried everything" — If you haven't found root cause, you haven't tried systematically.

## Quick Reference

1. Investigate → 2. Analyze → 3. Hypothesize → 4. Fix + regression test
