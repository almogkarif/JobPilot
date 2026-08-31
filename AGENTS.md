# AGENTS.md — Project Engineering Rules

These rules apply to every Codex task in this repository unless explicitly overridden by the user.

Bias toward correctness, caution, and minimal changes over speed on non-trivial work.
Use judgment for trivial tasks.

## Rule 1 — Understand Before Coding

Before changing code:

- Inspect the relevant implementation.
- Read immediate callers, exports, shared utilities, tests, and configuration when relevant.
- Infer intent from the existing codebase and tests before inventing new behavior.
- State material assumptions when they affect the implementation.

Do not stop for minor ambiguity that can be safely resolved from the repository.

Ask the user only when:
- multiple materially different interpretations remain,
- the choice could cause destructive or incompatible behavior,
- or the required information cannot reasonably be inferred.

Never silently guess about important behavior.

---

## Rule 2 — Simplicity First

Implement the minimum change that fully solves the requested problem.

Do not add:
- speculative features,
- unnecessary abstractions,
- generalized frameworks for one-off behavior,
- unrelated cleanup.

Prefer straightforward code over clever code.

If the solution becomes significantly more complicated than the problem appears to require, reassess before continuing.

---

## Rule 3 — Surgical Changes

Touch only what is necessary for the requested task.

Do not:
- refactor unrelated working code,
- rename unrelated symbols,
- reformat unrelated files,
- rewrite comments unnecessarily,
- "improve" adjacent code without a reason tied to the task.

Match the existing code style and architecture.

Preserve existing behavior unless the task explicitly requires changing it.

---

## Rule 4 — Goal-Driven Execution

Translate the request into concrete success criteria before implementation.

Work toward the observable result, not merely completion of a list of edits.

After implementation, verify the success criteria using the strongest practical evidence available:
- tests,
- direct execution,
- static inspection,
- or comparison with existing behavior.

Iterate when verification reveals a problem.

Do not declare completion merely because code was written.

---

## Rule 5 — Deterministic Logic Stays Deterministic

When implementing application behavior, use deterministic code for deterministic problems.

Use LLM/model reasoning only when the product requirement genuinely requires judgment such as:
- classification,
- extraction from unstructured text,
- summarization,
- drafting,
- semantic interpretation.

Do not introduce model calls for:
- routing,
- retries,
- exact transformations,
- validation that normal code can perform,
- deterministic business rules.

If normal code can reliably answer the question, normal code should answer it.

---

## Rule 6 — Keep Context Efficient

Do not waste context on repetitive output or unnecessary restatement.

For long tasks:
- maintain a concise understanding of what changed,
- keep track of verified vs unverified work,
- avoid repeatedly rereading large unrelated files,
- preserve important decisions before context becomes crowded.

Do not sacrifice correctness merely to reduce context usage.

---

## Rule 7 — Surface Conflicts, Don't Average Them

If two implementations, conventions, requirements, or tests conflict, do not create a hybrid accidentally.

Determine which one should govern using evidence such as:
1. explicit user instructions,
2. current tests,
3. current production code,
4. newer implementation,
5. repository conventions.

Explain meaningful conflicts when they affect the result.

Do not silently preserve obsolete behavior just because it exists somewhere in the repository.

---

## Rule 8 — Read Before You Write

Before adding or modifying behavior, inspect enough surrounding code to understand its dependencies.

At minimum, when relevant, inspect:
- the target function/module,
- immediate callers,
- imported/shared utilities,
- data models or schemas involved,
- tests covering the behavior.

Do not assume a component is isolated merely because the requested change looks local.

---

## Rule 9 — Tests Verify Intent

Tests should protect meaningful behavior, not implementation trivia.

When fixing a bug:
- add or update a regression test when practical,
- ensure the test would fail without the fix,
- test the externally meaningful behavior where possible.

Do not weaken tests merely to make them pass.

Do not replace a useful behavioral assertion with a less meaningful assertion unless the expected behavior itself changed.

---

## Rule 10 — Maintain a Verifiable Working State

After significant changes, make sure you can clearly identify:
- what changed,
- what remains unchanged,
- what has been verified,
- what remains unverified.

Do not continue stacking speculative fixes on top of an unknown state.

For multi-step tasks, verify important intermediate assumptions before building further work on them.

Avoid unnecessary progress narration unless the user asks for it.

---

## Rule 11 — Follow the Codebase

Conformance to the existing project is more important than personal style preferences.

Reuse existing:
- patterns,
- helpers,
- naming conventions,
- architecture,
- dependency choices,
- error-handling conventions.

If an existing convention is genuinely harmful to the requested change, surface the issue rather than silently introducing a competing convention.

---

## Rule 12 — Fail Loud

Never claim stronger verification than actually occurred.

Examples:

- Do not say "tests pass" if some relevant tests failed.
- Do not say "all tests pass" if tests were skipped.
- Do not say behavior was verified if it was only inferred from reading code.
- Do not hide warnings, skipped work, unsupported environments, or unresolved uncertainty.

Clearly distinguish:
- verified,
- partially verified,
- and not verified.

---

## Rule 13 — Supabase Egress Is a Hard Resource Budget

Treat Supabase egress as a production safety constraint. The Free organization has
a 5 GB uncached-egress quota per billing cycle; crossing it can make every project
return HTTP 402 until the next cycle.

Before changing startup tasks, scheduled jobs, polling, database queries, exports,
file delivery, screenshots, or worker downloads:

- Read `docs/SUPABASE_EGRESS.md` and complete its impact check.
- Estimate calls per hour/day, rows per call, and worst-case bytes per row/file.
- Never load the full job catalog or long `Job.description` values during startup,
  health checks, polling, reconciliation, or unchanged-item scans.
- Use SQL aggregates, pagination, `load_only`, or `defer` for bounded responses.
- Do not use `SELECT *` semantics when a smaller projection answers the question.
- Do not repeatedly download unchanged Storage objects; cache or reuse them when
  the runtime persists long enough to make that effective.
- Keep UI polling responses small and stop polling when the relevant UI is closed.
- Make legacy backfills and repair passes explicit, versioned, one-time operations;
  never run a whole-catalog repair on every process restart.

For any change that can affect egress, add or update a regression test in
`tests/test_supabase_egress_optimization.py`. Do not deploy if the worst-case
estimate is unbounded or if the relevant egress tests fail. After deployment,
compare the Supabase daily egress trend before triggering bulk retries or scans.

---

# Repository Safety Rules

## Preserve Existing User Work

Before making substantial edits, inspect the working tree when possible.

Do not overwrite or discard existing user changes.

Never use destructive Git operations such as:

- `git reset --hard`
- destructive checkout/restore of user work
- force push

unless explicitly instructed by the user and the consequences are clear.

---

## Dependencies

Do not add or upgrade production dependencies unless necessary for the task.

Before introducing a dependency, check whether the repository already contains an appropriate solution.

Prefer the standard library or existing dependencies when practical.

---

## Database and Persistent Data

Treat database changes as potentially destructive.

Do not:
- drop data,
- recreate databases,
- remove columns containing existing data,
- perform destructive migrations

unless explicitly required.

Prefer backward-compatible schema changes and safe defaults.

---

## Testing Workflow

After modifying code:

1. Run the narrowest relevant tests first.
2. Fix failures caused by the change.
3. Run broader tests when practical and justified by the scope of the change.
4. Review skipped tests separately from passing tests.

A skipped test is not a passed test.

If the full suite cannot be run, state exactly what was and was not executed.

---

## Final Verification

Before considering a coding task complete:

- inspect the final diff,
- check for unintended unrelated modifications,
- verify requested behavior,
- run relevant tests,
- inspect obvious edge cases,
- report any remaining uncertainty.

The final result should explain:
- what changed,
- what was verified,
- any tests not run or skipped,
- any remaining risks or limitations.

---

# Git Rules

Do not commit or push unless the user explicitly asks Codex to do so.

Do not amend, rewrite, squash, rebase, or force-push existing history unless explicitly requested.

Do not discard user changes in order to obtain a clean working tree.

---

# User Instructions Take Priority

A direct instruction from the user for the current task overrides these project defaults.

When an explicit current-task instruction conflicts with this file, follow the user's instruction unless doing so would be unsafe or technically impossible.
