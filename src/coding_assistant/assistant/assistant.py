from pathlib import Path
from logging import getLogger
import inspect

from ..config.config import Config
from ..memory.dispatch import create_architecture
from ..runtime.logger import Logger
from ..runtime.session import QuerySession

from ..models.operations import resolve_model_config

from ..providers.dispatch import create_llm

from ..tools.api import ToolsAPI
from ..utils import RecoverableError, CommandError

logger = getLogger(__name__)

class Assistant:

    def __init__(
            self,
            instructions: str,
            repo_path: Path,
            config: Config
    ) -> None:

        model_data, reasoning = resolve_model_config(
            model_name=config.model_name,
            reasoning=config.reasoning
        )

        self.tools_api = ToolsAPI(
            repo_path=repo_path,
            blocked_files=config.blocked_files,
            blocked_dirs=config.blocked_dirs
        )

        self.architecture, self.memory = create_architecture(
            name=config.architecture,
            api=self.tools_api
        )

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
        try:
            with QuerySession(
                query=query,
                query_logger=self.logger,
                memory=self.memory
            ) as session:
                with self.tools_api as api:
                    return self.architecture.run(
                        approval_handler=self.get_approval,
                        session=session,
                        api=api,
                        llm=self.llm,
                        max_iters=self.config.max_iters
                    )

        except Exception:
            try:
                self.logger.log()
            except Exception:
                logger.exception("Failed to persist query log after query failure.")

            raise

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
            f"Total cost (USD): ${self.logger.total_cost_usd():f}"
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
