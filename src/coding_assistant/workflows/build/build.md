# Build Workflow

Goal: create the requested implementation directly with minimal
exploration, tool usage, and context growth.

1. Determine the minimal build.

   * Identify the smallest set of files and behavior required.
   * Inspect the repository only when existing files, constraints, or
     requested integrations matter.
   * Do not search the codebase merely because files exist.

2. Implement directly.

   * Create the required files and code.
   * Keep the implementation simple and self-contained where possible.
   * Avoid abstractions, dependencies, configuration, or extra features
     not required by the request.
   * Do not re-read or search code you just created merely to review or
     confirm it.

3. Inspect only when needed.

   * Search or read existing code only if the requested build depends on it.
   * After implementation, inspect generated code only when a concrete
     issue, failed edit, or failed verification gives a reason to do so.

4. Verify proportionally.

   * Use the smallest useful existing check when verification is valuable.
   * Prefer one verification after implementation.
   * If verification cannot run because of the environment, stop unless
     the failure indicates an implementation problem.

5. Finish immediately.

   * Stop when the requested build is complete.
   * Do not continue exploring, refactoring, optimizing, or reviewing
     unrelated code.
   * Report concisely what was created and any meaningful verification
     limitation.