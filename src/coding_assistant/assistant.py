from pathlib import Path
import inspect
import json

from coding_assistant.config import Config
from coding_assistant.memory.memory import Memory
from coding_assistant.memory.schema import MemoryElement, QueryRecord
from coding_assistant.runtime.logger import Logger
from coding_assistant.runtime.runner import run
from coding_assistant.runtime.session import QuerySession

from coding_assistant.models.operations import resolve_model_config

from coding_assistant.providers.dispatch import create_llm

from coding_assistant.tools.api import ToolsAPI
from coding_assistant.utils import RecoverableError, CommandError, format_context_structure


class Assistant:

    _compression_threshold_percent = 50.0
    _compression_warning_percent = 85.0
    _automatic_compression_percent = 90.0
    _post_compression_warning_percent = 30.0

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
        percentage = self._context_percentage()
        if percentage > self._compression_warning_percent:
            print(
                f'\nContext usage is {percentage:.2f}%. '
                'Consider running /compress.\n'
            )
        return run(
            query,
            llm=self.llm,
            memory=self.memory,
            tools_api=self.tools_api,
            logger=self.logger,
            approval_handler=self.get_approval,
            before_model_call=self._check_loop_context,
        )

    def _check_loop_context(self, session: QuerySession) -> None:
        self._update_context_size()
        percentage = self._context_percentage()
        historical_elements = self.memory.elements[:session.memory_start_index]
        has_uncompressed_history = any(
            not isinstance(element, QueryRecord) for element in historical_elements
        )
        if percentage > self._automatic_compression_percent and has_uncompressed_history:
            before_tokens = self.memory.context_size
            before_is_estimate = self.memory.context_size_is_estimate
            active_elements = self.memory.elements[session.memory_start_index:]
            result = self._compress_memory(active_elements)
            session.memory_start_index = len(self.memory.query_records)
            session.query_log.compressions.append({
                'before_tokens': before_tokens,
                'before_is_estimate': before_is_estimate,
                'after_tokens': self.memory.context_size,
                'after_is_estimate': self.memory.context_size_is_estimate,
                'retained_active_elements': len(active_elements),
            })
            print(
                f'\nAutomatic compression: context exceeded '
                f'{self._automatic_compression_percent:g}% ({percentage:.2f}%).\n'
                f'{result}\n'
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
            f"Total tokens: {usage.total_tokens}\n\n"
            f"Reasoning tokens: {usage.reasoning_tokens}\n"
            f"Cached input tokens: {usage.cached_input_tokens}\n"
            f"Cache write tokens: {usage.cache_write_tokens}\n\n"
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
        self._update_context_size()
        return self._format_context_size()

    def _update_context_size(self) -> None:
        self.memory.context_size = self.llm.token_count(self._prefix() + self.memory.format_context())
        self.memory.context_size_is_estimate = True

    def _format_context_size(self) -> str:
        percentage = self._context_percentage()
        source = (
            'approximate (local token count)'
            if self.memory.context_size_is_estimate
            else 'last API input'
        )
        return (
            f'Context: {self.memory.context_size:,} / '
            f'{self.model_data.context_window:,} tokens\n'
            f'Usage: {percentage:.2f}%\n'
            f'Measurement: {source}'
        )

    def _context_percentage(self) -> float:
        return self.memory.context_size / self.model_data.context_window * 100

    def _prefix(self) -> str:
        schemas = self.llm.tool_schema_contract(self.tools_api.schemas())
        return self.llm.instructions + '\n' + json.dumps(schemas, ensure_ascii=False) + '\n'

    @_command()
    def compress(self) -> str:
        """Replace memory elements with the accumulated query records."""
        self._update_context_size()
        return self._compress_memory()

    def _compress_memory(self, active_elements: list[MemoryElement] | None = None) -> str:
        percentage = self._context_percentage()
        if percentage < self._compression_threshold_percent:
            return (
                f'Compression failed: context is below the '
                f'{self._compression_threshold_percent:g}% threshold.\n\n'
                f'{self._format_context_size()}'
            )
        compressed_elements = [*self.memory.query_records, *(active_elements or [])]
        compressed_context = (
            format_context_structure(tag='memory', structure=compressed_elements)
            if compressed_elements else ''
        )
        context_size = self.llm.token_count(self._prefix() + compressed_context)
        projected_percentage = context_size / self.model_data.context_window * 100
        if projected_percentage > self._post_compression_warning_percent:
            print(
                f'\nCompression preview: estimated context would remain at '
                f'{projected_percentage:.2f}%, above the '
                f'{self._post_compression_warning_percent:g}% target.\n\n'
                'Consider splitting the task or choosing a model with a larger context window.\n'
                'A larger-context model may cost more, and switching models can lose '
                'existing prompt-cache reuse. A larger window does not reduce the input token count.\n'
                'Compression will proceed; the run will continue.\n'
            )
        self.memory.compress(active_elements)
        self.memory.context_size = context_size
        self.memory.context_size_is_estimate = True
        retained = (
            f'Active query preserved: {len(active_elements)} elements.\n'
            if active_elements else ''
        )
        return (
            f'Memory successfully compressed into '
            f'{len(self.memory.query_records)} query records.\n\n'
            f'{retained}'
            f'{self._format_context_size()}'
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
            f"/{command.__name__}\n  {inspect.getdoc(command)}"
            for command in commands
        ]

        return '\n\n'.join(descriptions)
