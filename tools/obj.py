from tools.content import (FunctionTool, FunctionTools,
                           read_symbol, read_file, list_files,
                           search_code, search_symbol, replace_in_file)

available_tools = FunctionTools(
    tools=[
        FunctionTool.from_func(
            func=read_file,
            tool_description=(
                "Read the contents of a text file inside the current repository. "
                "Use this when you need to inspect the implementation of a known file."
            ),
            property_descriptions={
                "path": (
                    "Path to the file relative to the repository root, "
                    "for example 'src/auth.py'."
                ),
                "start_line": (
                    "Optional 1-based line number where reading starts. "
                    "If omitted, reading starts at the beginning of the file."
                ),
                "end_line": (
                    "Optional 1-based line number where reading ends, inclusive. "
                    "If omitted, reading continues to the end of the file."
                ),
            },
            additional_properties=False
        ),

        FunctionTool.from_func(
            func=list_files,
            tool_description=(
                "List files and directories at a path inside the current repository. "
                "Use this to explore the repository structure when you do not yet know "
                "which file is relevant. "
                "Do not use this tool when the target file or files are already known."
            ),
            property_descriptions={
                "path": (
                    "Directory path relative to the repository root. "
                    "Use '.' for the repository root."
                )
            },
            additional_properties=False
        ),

        FunctionTool.from_func(
            func=search_code,
            tool_description=(
                "Search repository contents for text or regular expressions. "
                "Do not use this tool to search for file names or to locate a file "
                "whose path is already known. "
                "Returns matching file paths, line numbers, and matching lines. "
                "Use this to locate known text such as symbol names, function names, "
                "class names, imports, error messages, or other textual references."
            ),
            property_descriptions={
                "query": (
                    "Text or regular expression to search for in repository contents."
                )
            },
            additional_properties=False
        ),

        FunctionTool.from_func(
            func=search_symbol,
            tool_description=(
                "Search Python files across the current repository for class, "
                "function, method, or nested function definitions. "
                "Returns matching symbols with their relative file path, qualified "
                "notation, kind, and source line range. "
                "Use this when the Python symbol name is known but its file location "
                "is not known. If no definition is found, use search_code to search "
                "for textual references."
            ),
            property_descriptions={
                "notation": (
                    "Python symbol name or qualified notation, such as 'run' or "
                    "'Assistant.run'. Do not include syntax such as 'class', 'def', "
                    "parentheses, or regular expressions."
                ),
            },
            additional_properties=False
        ),

        FunctionTool.from_func(
            func=read_symbol,
            tool_description=(
                "Read the source code of a specific class, function, or method "
                "from a known Python file using its qualified notation. "
                "Use this when both the target file and symbol are already known."
            ),
            property_descriptions={
                "path": (
                    "Path to the Python file relative to the repository root."
                ),
                "notation": (
                    "Exact qualified notation of the symbol to read, such as "
                    "'Assistant.run' or 'Factory.losses'."
                ),
            },
            additional_properties=False
        ),

        FunctionTool.from_func(
            func=replace_in_file,
            tool_description=(
                "Replace a specific piece of text in a file. "
                "The replacement can be restricted to a line range. "
                "The target text must occur exactly once within the selected range; "
                "otherwise, the operation fails. "
                "Use this to make precise edits to existing files without rewriting "
                "the entire file."
            ),
            property_descriptions={
                "path": (
                    "Path to the file relative to the repository root."
                ),
                "old_text": (
                    "Exact text to find and replace. It must occur exactly once within "
                    "the selected line range."
                ),
                "new_text": (
                    "Text that will replace old_text."
                ),
                "start_line": (
                    "Optional 1-based first line of the region in which to search for "
                    "old_text. If omitted, the search starts at the beginning of the file."
                ),
                "end_line": (
                    "Optional 1-based last line of the region in which to search for "
                    "old_text. If omitted, the search continues to the end of the file."
                ),
            },
            additional_properties=False
        )
    ]
).serialize()