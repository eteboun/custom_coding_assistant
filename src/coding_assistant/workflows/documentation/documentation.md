# Documentation Workflow

Goal: create or update documentation that accurately reflects the relevant codebase, with only the inspection necessary to support the documentation.

1. Determine the documentation scope.

   * Identify what the requested documentation must explain and which parts of the codebase provide the necessary facts.
   * Distinguish information that must be verified from details that are unnecessary for the requested documentation.
   * Form a minimal inspection plan before using tools.
   * Do not output the plan.
   * Do not assume implementation details that can be verified from the repository.

2. Gather evidence efficiently.

   * Use `repo_tree` or `list_files` when repository structure is relevant to the documentation.
   * Prefer `search_symbol`, `read_symbol`, and `search_code` when specific behavior, APIs, configuration, commands, or implementation details need to be located.
   * Use `read_file` when a complete or substantial file is genuinely useful for understanding what must be documented.
   * Documentation tasks may require broader reading than targeted code changes, but inspect only files relevant to the requested documentation.
   * Stop gathering evidence once the documentation can be written accurately.

3. Determine the minimum documentation content.

   * Include only information supported by the inspected repository or explicitly provided by the user.
   * Match the requested documentation type and scope.
   * Describe externally useful behavior, setup, usage, structure, interfaces, or implementation details only when relevant.
   * Do not invent commands, dependencies, configuration, behavior, guarantees, or project conventions.
   * Do not document unrelated implementation details merely because they were discovered during inspection.

4. Write or update the documentation.

   * Create or modify only the documentation files required by the request.
   * Preserve existing documentation structure and style when updating an existing document.
   * Keep documentation concise, accurate, and consistent with the current implementation.
   * Do not modify production code solely to make the documentation easier to write.
   * Treat a successful edit or creation result as confirmation that it was applied; do not re-read the documentation only to confirm it.

5. Verify only when needed.

   * Re-check source code only if a claim remains uncertain or conflicting evidence was found.
   * Do not run the application, tests, or build merely to verify documentation when the necessary facts are already established from inspected code.
   * When generated documentation contains commands or examples whose correctness cannot be established from the repository, avoid presenting them as verified facts.

6. Finish immediately.

   * Stop once the requested documentation accurately reflects the relevant implementation.
   * Do not continue exploring the repository, improving unrelated documentation, or modifying code.
   * Report concisely what documentation was created or updated and any material limitation in what could be verified.