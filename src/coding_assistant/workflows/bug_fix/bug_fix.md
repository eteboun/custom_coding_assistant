Bug Fix Workflow

Goal: identify the existing failure, make the smallest correct fix, and stop with minimal tool usage and context growth.

1. Plan briefly before acting.

   * Identify what must be located, what evidence is needed, and the smallest likely fix.
   * Do not output the plan.
   * Avoid speculative inspection.

2. Locate the relevant code efficiently.

   * Prefer `search_symbol`, `read_symbol`, and `search_code` when they can directly identify the relevant implementation.
   * Choose between them according to their tool descriptions and the task; do not call them mechanically or try all of them just because they are preferred.
   * Prefer targeted search over repository-wide reading.
   * Use `read_file` as a fallback when search/symbol tools cannot provide enough context, when the relevant location is already known, or when additional surrounding lines are required.
   * Read the smallest useful range.

3. Diagnose before editing.

   * Determine the actual failure point from inspected code.
   * Do not redesign surrounding architecture unless the bug cannot be fixed otherwise.
   * Stop inspecting once there is enough evidence to make the fix.

4. Apply the smallest correct change.

   * Modify only code required to fix the reported behavior.
   * Prefer small targeted replacements.
   * Batch independent edits to the same file when possible.
   * Do not add unrelated validation, refactors, cleanup, tests, comments, or abstractions.
   * Treat a successful edit result as confirmation that the edit was applied; do not re-read or search modified code only to confirm it.

5. Verify proportionally.

   * Skip verification when the change is simple enough that inspected code and the edit result make correctness clear.
   * When verification is useful, use the smallest relevant existing check or command.
   * Prefer one targeted verification after editing.
   * Do not construct broad ad-hoc test harnesses for simple fixes.
   * If verification fails because of the execution environment, stop unless the failure gives evidence that the target code itself is wrong.

6. Finish immediately.

   * Stop when the reported bug is fixed.
   * Do not continue exploring, reconsider the implementation, or perform extra checks without new evidence of a problem.
   * Report only what was fixed and any verification limitation that materially matters.
