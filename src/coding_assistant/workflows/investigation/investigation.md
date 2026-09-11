Investigation Workflow

Goal: answer the user's question from repository evidence with the minimum inspection, tool usage, and context growth. Do not modify code unless explicitly requested.

1. Determine what must be established.

   * Identify the specific question the investigation must answer.
   * Internally determine what code, behavior, relationship, or evidence would be sufficient to answer it.
   * Do not output the plan.
   * Do not inspect code without a concrete reason related to the question.

2. Locate relevant code efficiently.

   * Prefer `search_symbol`, `read_symbol`, and `search_code` when they can directly locate the relevant implementation, usage, dependency, or data flow.
   * Choose tools according to their descriptions and the task; do not call all preferred tools mechanically.
   * Prefer targeted search over broad repository inspection.
   * Use `read_file` as a fallback when search/symbol tools cannot provide enough context, the relevant location is already known, or additional surrounding code is necessary.
   * Read only the smallest useful ranges.

3. Follow evidence only as far as necessary.

   * Trace callers, dependencies, state, or data flow only when required to answer the question.
   * Do not explore adjacent code merely because it may be related.
   * Do not inspect alternative implementations once the relevant behavior is sufficiently established.
   * Stop investigating as soon as the available evidence supports a confident answer.
   * If the inspected code is insufficient, make the next tool call specifically target the missing information.

4. Avoid redundant inspection.

   * Do not search for information already established by inspected code.
   * Do not re-read unchanged content.
   * Do not use another tool solely to confirm a result that is already clear.
   * If a search result provides enough context to answer the question, do not read the containing file unnecessarily.
   * Before each additional tool call, require a concrete unanswered question that it is expected to resolve.

5. Preserve investigation scope.

   * Do not modify files, refactor code, add tests, or fix issues discovered during investigation unless the user requested changes.
   * Do not broaden the task into a general code review.
   * Mention unrelated issues only when they materially affect the answer to the user's question.

6. Verify only when necessary.

   * Do not run code merely to confirm behavior that is already clear from inspected code.
   * Use execution only when the question depends on runtime behavior that static inspection cannot establish reliably.
   * Use the smallest targeted command necessary.
   * If execution is blocked by the environment, stop unless another inspection is necessary to answer the original question.

7. Finish immediately.

   * Stop using tools once the user's question can be answered from inspected evidence.
   * Answer only what was asked, with enough implementation detail to support the conclusion.
   * Clearly distinguish confirmed repository behavior from any inference when necessary.
