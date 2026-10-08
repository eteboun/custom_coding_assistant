from pathlib import Path
import inspect
import json

from coding_assistant.config import Config
from coding_assistant.memory.memory import Memory
from coding_assistant.runtime.logger import Logger
from coding_assistant.runtime.runner import run

from coding_assistant.models.operations import resolve_model_config

from coding_assistant.providers.dispatch import create_llm

from coding_assistant.tools.api import ToolsAPI
from coding_assistant.utils import RecoverableError, CommandError, format_context_structure


class Assistant:

    _compression_threshold_percent = 50.0

    def __init__(
            self,
            instructions: str,
            repo_path: Path,
            config: Config,
            *,
            memory: Memory | None = None,
    ) -> None:

        model_data, reasoning = resolve_model_config(
            model_name=config.model_name,
            reasoning=config.reasoning
        )
        self.model_data = model_data

        self.tools_api = ToolsAPI(
            repo_path=repo_path,
            blocked_files=config.blocked_files,
            blocked_dirs=config.blocked_dirs
        )

        self.memory = memory if memory is not None else Memory()

        self.logger = Logger(
            log_path=config.log_path,
            model_data=model_data,
        )

        self.llm = create_llm(
            instructions=instructions,
            model_data=model_data,
            reasoning=reasoning,
            max_iters=config.max_iters
        )

        self.config = config
        self.mapping = self._get_command_function_mapping()

        print("Assistant initialized")

    @staticmethod
    def get_approval(message: str) -> bool:
        approval = input(f"{message} [y/N]: ")
        return approval.strip().lower() == "y"

    def _run_query(self, query: str) -> str:
        return run(
            query,
            llm=self.llm,
            memory=self.memory,
            tools_api=self.tools_api,
            logger=self.logger,
            approval_handler=self.get_approval,
        )

    @staticmethod
    def _command():
        def wrapper(func):
            func.is_command = True
            return func
        return wrapper

    def query(self, query: str) -> str:
        query = query.strip()

        try:
            if query.startswith("/"):
                command = self._parse_command(query)

                if command in self.mapping:
                    return self._run_command(
                        command=command
                    )

                raise CommandError(
                    f"Command '{command}' not found."
                )

            return self._run_query(
                query=query
            )

        except RecoverableError as e:
            return str(e)

    def _run_command(self, command: str) -> str:
        func = self.mapping[command]
        return func(self).strip()

    @staticmethod
    def _parse_command(query: str) -> str:
        return query.removeprefix("/")

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

    @_command()
    def usage(self) -> str:
        """
        Shows current token usage information.
        """

        usage = self.logger.total_usage()

        return (
            f"Input tokens: {usage.input_tokens}\n"
            f"Output tokens: {usage.output_tokens}\n"
            f"Total tokens: {usage.total_tokens}\n"
            f"Reasoning tokens: {usage.reasoning_tokens}\n"
            f"Cached input tokens: {usage.cached_input_tokens}\n"
            f"Cache write tokens: {usage.cache_write_tokens}\n"
            f"Total cost (USD): ${usage.total_cost:f}"
        )

    @_command()
    def model(self) -> str:
        """
        Shows current model if no model name is provided.
        """

        return (
            f"Current model: {self.llm.model_data.id}"
        )

    @_command()
    def reasoning(self) -> str:
        """
        Shows current reasoning level if no reasoning level is provided.
        """

        return (
            f"Current config reasoning: {self.config.reasoning}\n"
            f"Current effective reasoning: {self.llm.reasoning}"
        )

    @_command()
    def context(self) -> str:
        """Show context token count and percentage of the model context window."""
        percentage = self._context_percentage()
        source = (
            'approximate tokenized prefix + memory size'
            if self.memory.context_size_is_estimate
            else 'last API input'
        )
        return (
            f'Context: {self.memory.context_size:,} / '
            f'{self.model_data.context_window:,} tokens ({percentage:.2f}%) '
            f'[{source}]'
        )

    def _context_percentage(self) -> float:
        return self.memory.context_size / self.model_data.context_window * 100

    def _prefix(self) -> str:
        schemas = self.llm.tool_schema_contract(self.tools_api.schemas())
        return self.llm.instructions + '\n' + json.dumps(schemas, ensure_ascii=False) + '\n'

    @_command()
    def compress(self) -> str:
        """Replace memory elements with the accumulated query records."""
        percentage = self._context_percentage()
        if percentage < self._compression_threshold_percent:
            return (
                f'Compression failed: context is below the '
                f'{self._compression_threshold_percent:g}% threshold.\n'
                f'{self.context()}'
            )
        compressed_context = (
            format_context_structure(tag='memory', structure=self.memory.query_records)
            if self.memory.query_records else ''
        )
        context_size = self.llm.token_count(self._prefix() + compressed_context)
        self.memory.compress()
        self.memory.context_size = context_size
        self.memory.context_size_is_estimate = True
        return (
            f'Memory successfully compressed into '
            f'{len(self.memory.query_records)} query records.\n'
            f'{self.context()}'
        )

    @_command()
    def log(self) -> str:
        """
        Logs current session state.
        """

        name = self.logger.log()
        return f"Successfully logged as {name}."

    @_command()
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
