import inspect

from collections.abc import Callable
from pathlib import Path

from .schema import ToolSchema, Parameters, Metadata, Approval
from .context import Invalidation, ToolOutput, Operation, UpdateScope
from .workspace import Workspace
from .sandbox import Sandbox


class Tools:
    def __init__(self,
                 repo_path: Path,
                 blocked_files: list[str],
                 blocked_dirs: list[str]
                 ) -> None:

        self.workspace = Workspace(
            repo_path=repo_path,
            blocked_files=blocked_files,
            blocked_dirs=blocked_dirs
        )
        self.sandbox = Sandbox(
            repo_path=repo_path,
            blocked_files=blocked_files,
            blocked_dirs=blocked_dirs,
        )

        self.function_mapping = self._tool_function_mapping()
        self.data_mapping = self._tool_data_mapping()

    @staticmethod
    def _tool(
            description: str,
            parameters: Parameters,
            metadata: Metadata,
            strict: bool = False
    ) -> Callable:

        def decorator(func):
            tool_data = ToolSchema.from_func(
                func=func,
                description=description,
                parameters=parameters,
                strict=strict,
                metadata=metadata
            )

            func.is_tool = True
            func.tool_data = tool_data

            return func

        return decorator

    def _tools(self):
        funcs = []

        for _, func in inspect.getmembers(self, predicate=inspect.ismethod):
            if getattr(func, "is_tool", False):
                funcs.append(func)
    
        return funcs

    def _tool_data_mapping(self) -> dict[str, ToolSchema]:
        return {
            tool.tool_data.name: tool.tool_data
            for tool in self._tools()
        }

    def _tool_function_mapping(self) -> dict[str, Callable]:
        return {
            tool.tool_data.name: tool
            for tool in self._tools()
        }

    def tools(self) -> list[str]:
        return [
            tool.__name__
            for tool in self._tools()
        ]

    @_tool(
        description=(
                "Read a known text file, optionally within a line range. "
        ),
        parameters=Parameters(
            properties={
                "path": {
                    "type": "string",
                    "description": "Repository-relative file path.",
                },
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional 1-based starting line.",
                },
                "end_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional 1-based ending line, inclusive.",
                }
            },
            required=["path", "start_line", "end_line"],
            additional_properties=False
        ),
        metadata=Metadata(
            update_scope=UpdateScope.FILE,
            update_when={
                Operation.UPDATE: Invalidation.REFRESH,
                Operation.DELETE: Invalidation.DISCARD
            }
        )
    )
    def read_file(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> ToolOutput:
        return self.workspace.read_file(
            path=path,
            start_line=start_line,
            end_line=end_line
        )

    @_tool(
        description=(
                "List files and directories inside a known repository directory."
        ),
        parameters=Parameters(
            properties={
                "path": {
                    "type": "string",
                    "description": "Repository-relative directory path. Use '.' for the root.",
                }
            },
            required=["path"],
            additional_properties=False,
        ),
        metadata=Metadata(
            update_scope=UpdateScope.REPOSITORY,
            update_when={
                Operation.ADD: Invalidation.REFRESH,
                Operation.DELETE: Invalidation.REFRESH
            }
        )
    )
    def list_directory(self, path: str) -> ToolOutput:
        return self.workspace.list_directory(
            path=path
        )

    @_tool(
        description=(
                "Find repository files whose paths match an optional glob pattern. "
                "If no pattern is provided, list repository files. "
                "Use this when relevant files are unknown but can be narrowed by path, filename, or extension."
        ),
        parameters=Parameters(
            properties={
                "pattern": {
                    "type": "string",
                    "description": (
                            "Optional glob pattern such as '*.py', "
                            "'src/**/*.ts', or '**/*test*'."
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of matching paths to return.",
                    "minimum": 1,
                    "default": 100
                }
            },
            required=[],
            additional_properties=False
        ),
        metadata=Metadata(
            update_scope=UpdateScope.REPOSITORY,
            update_when={
                Operation.ADD: Invalidation.REFRESH,
                Operation.DELETE: Invalidation.REFRESH
            }
        )
    )
    def search_files(
            self,
            pattern: str | None = None,
            max_results: int = 100
    ) -> ToolOutput:
        return self.workspace.search_files(
            pattern=pattern,
            max_results=max_results
        )

    @_tool(
        description="Search repository contents for text or regex matches.",
        parameters=Parameters(
            properties={
                "query": {
                    "type": "string",
                    "description": "Text or regular expression to search for."
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Surrounding lines per match."
                },
                "max_output_lines": {
                    "type": "integer",
                    "description": "Maximum output lines."
                },
                "regex": {
                    "type": "boolean",
                    "description": (
                            "Whether to interpret text as a ripgrep regular expression. "
                            "If false, text is matched literally."
                    )
                }
            },
            required=["query"],
            additional_properties=False
        ),
        metadata=Metadata(
            update_scope=UpdateScope.REPOSITORY,
            update_when={
                Operation.ADD: Invalidation.REFRESH,
                Operation.DELETE: Invalidation.REFRESH,
                Operation.UPDATE: Invalidation.REFRESH
            }
        )
    )
    def search_text(self,
                    query: str,
                    context_lines: int = 2,
                    regex: bool = False,
                    max_output_lines: int = 100
                    ) -> ToolOutput:
        return self.workspace.search_text(
            text=query,
            context_lines=context_lines,
            max_output_lines=max_output_lines,
            regex=regex
        )

    @_tool(
        description=(
                "Apply a Codex-style patch containing one or more file operations. "
                "Supported file operations are only: "
                "'*** Update File: <path>', "
                "'*** Add File: <path>', and "
                "'*** Delete File: <path>'. "
                "The patch must start with '*** Begin Patch' and end with '*** End Patch'. "
                "Update File operations may contain one or more hunks separated by '@@'. "
                "Within update hunks, lines prefixed with ' ' are unchanged context, "
                "'-' lines are removed, and '+' lines are added. "
                "Update hunks are matched against the original file state, must match exactly once, "
                "and must not overlap. "
                "Use only enough unchanged context to identify each target uniquely. "
                "Add File content must consist only of '+' prefixed lines. "
                "Delete File operations must not contain file content. "
                "Unsupported operations or metadata must not be used."
        ),
        parameters=Parameters(
            properties={
                "patch": {
                    "type": "string",
                    "description": (
                            "Complete patch in Codex-style format. "
                            "Supported structure:\n"
                            "*** Begin Patch\n"
                            "*** Update File: <path>\n"
                            "@@\n"
                            " <unchanged context>\n"
                            "-<removed line>\n"
                            "+<added line>\n"
                            "@@\n"
                            " <another hunk>\n"
                            "*** Add File: <path>\n"
                            "+<new file content>\n"
                            "*** Delete File: <path>\n"
                            "*** End Patch\n"
                            "Supported Update File hunks are '@@'-separated contiguous edit regions "
                            "using only ' ', '-', and '+' line prefixes."
                    ),
                },
                "change_summary": {
                    "type": "string",
                    "description": (
                            "A concise semantic summary of what this mutation "
                            "is intended to change and why. Describe behavior "
                            "or state changes, not patch mechanics."
                    )
                }
            },
            required=["patch", "change_summary"],
            additional_properties=False,
        ),
        strict=True,
        metadata=Metadata(
            update_scope=None,
            update_when={},
            mutative=True
        )
    )
    def apply_patch(
            self,
            patch: str,
    ) -> ToolOutput:
        return self.workspace.apply_patch(
            patch=patch
        )

    @_tool(
        description="Delete an empty directory from the repository.",
        parameters=Parameters(
            properties={
                "path": {
                    "type": "string",
                    "description": "Repository-relative path for the directory to be deleted.",
                },
                "change_summary": {
                    "type": "string",
                    "description": (
                            "A concise semantic summary of what this mutation "
                            "is intended to change and why. Describe the purpose "
                            "of removing the directory, not the deletion mechanics."
                    )
                }
            },
            required=["path", "change_summary"],
            additional_properties=False,
        ),
        metadata=Metadata(
            update_scope=None,
            update_when={},
            mutative=True
        )
    )
    def delete_dir(self, path: str) -> ToolOutput:
        return self.workspace.delete_dir(
            path=path
        )

    @_tool(
        description=(
            "Return the repository's directory and file structure without "
            "reading file contents. Useful for understanding the repository "
            "layout and locating potentially relevant files."
        ),
        parameters=Parameters(
            properties={},
            required=[],
            additional_properties=False
        ),
        metadata=Metadata(
            update_scope=UpdateScope.REPOSITORY,
            update_when={
                Operation.ADD: Invalidation.REFRESH,
                Operation.DELETE: Invalidation.REFRESH
            }
        )
    )
    def repo_tree(self) -> ToolOutput:
        return self.workspace.repo_tree()

    @_tool(
        description=(
            "Execute a shell command in the repository sandbox for testing, "
            "building, validation, or runtime diagnostics. Do not use this tool "
            "for reading, searching, or intentionally modifying repository source "
            "files when a dedicated tool exists."
        ),
        parameters=Parameters(
            properties={
                "command": {
                    "type": "string",
                    "description": "The shell command to execute."
                }
            },
            required=["command"],
            additional_properties=False
        ),
        metadata=Metadata(
            update_scope=None,
            update_when={},
            approval=Approval(
                template="Agent wants to run this command: {command}"
            )
        )
    )
    def run_command(self, command: str) -> ToolOutput:
        return self.sandbox.run_command(
            command=command
        )
