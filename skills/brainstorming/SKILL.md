---
name: brainstorming
description: You MUST use this before any creative work - creating features, building components, adding functionality, or modifying behavior. Explores user intent, requirements and design before implementation.
---

# Brainstorming Ideas Into Designs

Help turn ideas into fully formed designs and specs through natural collaborative dialogue.

Start by understanding the current project context, then ask questions one at a time to refine the idea. Once you understand what you're building, present the design and get user approval.

<HARD-GATE>
Do NOT write any code, scaffold any project, or take any implementation action until you have presented a design and the user has approved it. This applies to EVERY project regardless of perceived simplicity.
</HARD-GATE>

## Anti-Pattern: "This Is Too Simple To Need A Design"

Every project goes through this process. A todo list, a single-function utility, a config change — all of them. "Simple" projects are where unexamined assumptions cause the most wasted work. The design can be short (a few sentences for truly simple projects), but you MUST present it and get approval.

## Checklist

Work through these items in order:

1. **Explore project context** — check files and docs to understand what already exists
2. **Ask clarifying questions** — one at a time, understand purpose/constraints/success criteria
3. **Propose 2-3 approaches** — with trade-offs and your recommendation
4. **Present design** — in sections scaled to their complexity, get user approval after each section
5. **Write design doc** — save the approved design to a file (e.g. `DESIGN.md`)
6. **Transition to implementation** — only after the user has approved the design

## The Process

**Understanding the idea:**

- Check the current project state first (files, docs)
- Before asking detailed questions, assess scope: if the request describes multiple independent subsystems, flag this immediately and help decompose — each sub-project gets its own design cycle
- For appropriately-scoped projects, ask questions **one at a time** to refine the idea
- Prefer multiple choice questions when possible, but open-ended is fine too
- Focus on: purpose (what problem is this solving?), constraints (what must it not do?), success criteria (how will we know it's done?)

**Proposing approaches:**

- Present 2-3 distinct approaches with trade-offs
- Give your recommendation and reasoning, but let the user decide

**Presenting the design:**

- Scale depth to complexity — a few sentences for simple projects, sections for complex ones
- Get explicit user approval before any implementation

**Anti-patterns to avoid:**

- Asking several questions at once (overwhelms; ask one at a time)
- Jumping to code before understanding the idea
- Presenting a single approach as if it were the only option

## Red Flags - STOP and Follow Process

| Thought | Reality |
|---------|---------|
| "I understand the request, let me just start" | You have assumptions that need checking. Ask. |
| "This is simple enough to skip the process" | Simple projects hide the most unexamined assumptions. |
| "I'll ask questions while coding" | Questions come first. Design is the contract. |
| "The user said 'just do it'" | Clarify whether that means "skip design" or "design quickly". |
