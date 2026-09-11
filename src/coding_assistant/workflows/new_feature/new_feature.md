New Feature Workflow

Goal: understand where the feature belongs, identify its impact, implement the smallest coherent version, and stop with minimal tool usage and context growth.

1. Plan before acting.

   * First determine where the feature should integrate into the existing codebase.
   * Identify which components, state, data flow, interfaces, files, or behaviors the feature may need to change.
   * Distinguish required changes from merely possible or related changes.
   * Form a minimal implementation plan before using edit tools.
   * Do not output the plan.
   * Do not start editing until the integration points and likely impact are sufficiently understood.

2. Locate the integration points efficiently.

   * Prefer `search_symbol`, `read_symbol`, and `search_code` when they can directly locate relevant implementations, callers, state, or existing patterns.
   * Choose tools according to their descriptions and the task; do not call all preferred tools mechanically.
   * Prefer targeted search over broad repository inspection.
   * Use `read_file` as a fallback when search/symbol tools do not provide enough context, the relevant location is already known, or surrounding code is necessary.
   * Read only the smallest ranges needed to understand the integration.

3. Determine the minimum feature scope.

   * Identify the smallest set of changes required for the requested feature to work correctly with the existing architecture.
   * Reuse existing patterns, abstractions, and data flow where appropriate.
   * Do not introduce new abstractions, dependencies, configuration, validation, or architecture unless the feature actually requires them.
   * Do not modify related areas merely because they could be improved.
   * Stop inspecting once the required integration points and effects are understood.

4. Implement according to the plan.

   * Make only the changes required by the feature.
   * Prefer small, targeted replacements.
   * Batch independent edits to the same file when they can be derived from the same known file state.
   * Keep behavior outside the requested feature unchanged unless modification is necessary for integration.
   * Remove code only when the feature directly makes it unused.
   * Treat a successful edit result as confirmation that the edit was applied; do not re-read or search modified code only to confirm it.

5. Reassess only when new evidence requires it.

   * Do not redesign the implementation after a successful edit merely because another design is possible.
   * Re-plan only if a tool result, failed edit, dependency, or inspected code reveals that the original plan cannot correctly implement the feature.
   * If re-planning is necessary, update only the affected part of the plan rather than restarting repository exploration.

6. Verify proportionally.

   * Skip verification when the feature is simple and correctness is clear from the inspected code and applied changes.
   * When verification is useful, use the smallest relevant existing check or command.
   * Prefer one targeted verification after all required edits.
   * Do not construct broad ad-hoc test harnesses for simple features.
   * If verification fails because of the execution environment, stop unless the failure provides evidence that the implementation itself is wrong.

7. Finish immediately.

   * Stop once the requested feature is implemented.
   * Do not continue exploring, re-reading, optimizing, refactoring, or checking unrelated behavior.
   * Report concisely what was added and any verification limitation that materially matters.
