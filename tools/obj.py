from tools.content import (FunctionTool, FunctionTools,
                           read_symbol, read_file, list_files,
                           search_code, search_symbol)

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
                "start_line": "Line number that the reading will be started.",
                "end_line": "Line number that the reading will be ended, inclusive."
            },
            additional_properties=False
        ),

        FunctionTool.from_func(
            func=list_files,
            tool_description=(
                "List files and directories at a path inside the current repository. "
                "Use this to explore the repository structure when you do not yet know "
                "which file is relevant."
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
                "Search the current repository for an exact text or regular expression. "
                "Returns matching file paths, line numbers, and matching lines. "
                "Use this to locate symbols, function names, classes, imports, "
                "error messages, or other known pieces of text."
            ),
            property_descriptions={
                "query": (
                    "Text or regular expression to search for in the repository."
                )
            },
            additional_properties=False
        ),

        FunctionTool.from_func(
            func=search_symbol,
            tool_description=(
                "Search Python files across the current repository for class, "
                "function, method, or nested function definitions. Returns matching "
                "symbols with their relative file path, qualified notation, kind, "
                "and source line range. Use this to locate Python definitions before "
                "reading their implementation. If no definition is found, use "
                "search_code to search for textual references."
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
                "from a Python file using its qualified notation. Use this when "
                "the target symbol is already known and only its implementation "
                "needs to be inspected."
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
        )
    ]
).serialize()