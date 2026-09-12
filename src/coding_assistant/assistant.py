from pathlib import Path
import inspect

from .ai.config import Config, config_reasoning_levels
from .ai.schemas import models_by_provider

from .llm import create_llm

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

        self.mapping = self._get_command_function_mapping()

        print("Assistant initialized")

    @staticmethod
    def _command(func):
        func.is_command = True
        return func

    def query(self, query: str) -> str:
        query = query.strip()

        if query.startswith("/"):
            command = query.removeprefix("/")

            if command in self.mapping:
                return self.mapping[command](self).strip() + '\n\n'

            return f"Command '{command}' not found.\n\n"

        return self.llm.run(query)

    @staticmethod
    def _get_command_functions():
        methods = inspect.getmembers(Assistant, predicate=inspect.isfunction)

        return [
            method
            for _, method in methods
            if getattr(method, "is_command", False)
        ]

    @staticmethod
    def _get_command_function_mapping():
        methods = inspect.getmembers(Assistant, predicate=inspect.isfunction)

        return {
            method.__name__: method
            for _, method in methods
            if getattr(method, "is_command", False)
        }

    @_command
    def usage(self) -> str:
        """
        Shows current token usage information.
        """

        usage = self.llm.logger.total_usage()

        return (
            f"Input tokens: {usage.input_tokens}\n"
            f"Output tokens: {usage.output_tokens}\n"
            f"Total tokens: {usage.total_tokens}\n"
            f"Reasoning tokens: {usage.reasoning_tokens}\n"
            f"Cached input tokens: {usage.cached_input_tokens}\n"
            f"Cache write tokens: {usage.cache_write_tokens}"
        )

    @_command
    def model(self) -> str:
        """
        Shows current model.
        """

        return (
            f"Current model: {self.llm.model_data.id}\n"
            f"Reasoning: {self.llm.config.reasoning}"
        )

    @_command
    def models(self) -> str:
        """
        Shows available models.
        """

        text: list[str] = []
        for provider, model_datas in models_by_provider.items():
            sub_text: list[str] = [f"Provider: {provider.capitalize()}"]

            for model_data in model_datas:
                sub_text.append(f" {model_data.id}")

            text.append('\n'.join(sub_text))

        return '\n\n'.join(text)

    @_command
    def reasoning_levels(self) -> str:
        """
        Shows valid reasoning levels.
        """

        return f"Valid reasoning levels: {', '.join(config_reasoning_levels)}."

    @_command
    def tools(self) -> str:
        """
        Shows available tools.
        """

        tools = '\n'.join(map(
            lambda t: '- ' + t,
            self.llm.tools.tools()
        ))

        return f"Available tools:\n{tools}"

    @_command
    def log(self) -> str:
        """
        Logs current session state.
        """

        log_output = self.llm.log()
        return log_output.message

    @_command
    def help(self) -> str:
        """
        Shows command descriptions.
        """

        commands = self._get_command_functions()

        descriptions = [
            f"/{command.__name__} -> {inspect.getdoc(command)}"
            for command in commands
        ]

        return '\n'.join(descriptions)
