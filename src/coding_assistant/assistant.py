from pathlib import Path
import inspect

from .ai.config import Config
from .ai.llm import create_llm

class Assistant:

    def __init__(
            self,
            instructions: str,
            repo_path: Path,
            config: Config
    ) -> None:
        self.llm = create_llm(
            instructions=instructions,
            repo_path=repo_path,
            config=config
        )

        print("Assistant initialized")

    @staticmethod
    def _command(func):
        name = func.__name__

        if not name.startswith("_command_"):
            raise NameError(
                "Invalid command function name"
            )

        func.is_command = True
        func.command_repr = "/" + name.removeprefix("_command_")

        return func

    def query(self, query: str) -> str:
        match query.strip():
            case "/usage":
                return self._command_usage()

            case "/model":
                return self._command_model()

            case "/help":
                return self._command_help()

            case _:
                return self.llm.run(query)

    @staticmethod
    def _get_command_functions():
        methods = inspect.getmembers(Assistant, predicate=inspect.isfunction)

        return [
            method
            for _, method in methods
            if method.is_command
        ]

    @_command
    def _command_usage(self) -> str:
        """
        Shows current token usage information.
        """

        usage = self.llm.logger.total_usage()

        return (
            f"Input tokens: {usage.input_tokens}\n"
            f"Output tokens: {usage.output_tokens}\n"
            f"Reasoning tokens: {usage.reasoning_tokens}\n"
            f"Total tokens: {usage.total_tokens}\n"
            f"Cached input tokens: {usage.cached_input_tokens}\n"
            f"Cache write tokens: {usage.cache_write_tokens}\n"
        )

    @_command
    def _command_model(self) -> str:
        """
        Shows current model.
        """

        return (
            f"Current model: {self.llm.model_data.id}\n"
            f"Reasoning: {self.llm.config.reasoning}"
        )

    @_command
    def _command_help(self) -> str:
        """
        Shows command descriptions.
        """

        commands = self._get_command_functions()

        descriptions = [
            f"{command.command_repr} -> {inspect.getdoc(command)}"
            for command in commands
        ]

        return '\n'.join(descriptions) + '\n\n'
