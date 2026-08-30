from tools.content import (FunctionTool, FunctionTools,
                           read_symbol, read_file, list_files, create_file,
                           search_code, search_symbol, replace_in_file)

available_tools = FunctionTools(
    tools=[
        FunctionTool.from_func(
            func=read_file,
            tool_description=(
                "Read a known text file in the repository, optionally within a line range."
            ),
            property_descriptions={
                "path": "Repository-relative file path.",
                "start_line": "Optional 1-based starting line.",
                "end_line": "Optional 1-based ending line, inclusive.",
            },
            additional_properties=False
        ),

        FunctionTool.from_func(
            func=list_files,
            tool_description=(
                "List files and directories in a repository directory. "
                "Use for repository exploration when the relevant file is unknown."
            ),
            property_descriptions={
                "path": "Repository-relative directory path. Use '.' for the root."
            },
            additional_properties=False
        ),

        FunctionTool.from_func(
            func=search_code,
            tool_description=(
                "Search repository contents for text or regex matches. "
                "Returns file paths, line numbers, and matching lines. "
                "Use for known text or references, not file-name lookup."
            ),
            property_descriptions={
                "query": "Text or regular expression to search for."
            },
            additional_properties=False
        ),

        FunctionTool.from_func(
            func=search_symbol,
            tool_description=(
                "Find Python class, function, method, or nested-function definitions "
                "when the symbol name is known but its file is not. "
                "Use search_code if no definition is found."
            ),
            property_descriptions={
                "notation": (
                    "Symbol name or qualified notation, e.g. 'run' or 'Assistant.run'."
                ),
            },
            additional_properties=False
        ),

        FunctionTool.from_func(
            func=read_symbol,
            tool_description=(
                "Read a Python class, function, or method when both its file "
                "and qualified notation are known."
            ),
            property_descriptions={
                "path": "Repository-relative Python file path.",
                "notation": (
                    "Exact qualified notation, e.g. 'Assistant.run' or 'Factory.losses'."
                ),
            },
            additional_properties=False
        ),

        FunctionTool.from_func(
            func=replace_in_file,
            tool_description=(
                "Replace an exact piece of existing file content. "
                "The text must occur exactly once within the selected line range."
            ),
            property_descriptions={
                "path": "Repository-relative file path.",
                "old_text": (
                    "Exact text copied from the file, preserving its content, "
                    "whitespace, indentation, and line breaks."
                ),
                "new_text": (
                    "Replacement text with the intended whitespace, indentation, "
                    "and line breaks."
                ),
                "start_line": "Optional 1-based starting line.",
                "end_line": "Optional 1-based ending line, inclusive.",
            },
            additional_properties=False
        ),

        FunctionTool.from_func(
            func=create_file,
            tool_description=(
                "Create a new file. Fails if the path already exists."
            ),
            property_descriptions={
                "path": "Repository-relative path for the new file.",
                "content": "Complete initial content of the file.",
            },
            additional_properties=False,
        )
    ]
).serialize()