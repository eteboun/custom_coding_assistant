from pathlib import Path
from logging import getLogger
import inspect

from .config import Config
from .logger import Logger, LLMToolEventLog, LLMFinalCallLog
from ..memory.memory import ActiveMemory, ShortMemory, LongMemory, ToolEvent

from ..models.models import models_by_provider
from ..providers.llm import create_llm

from ..tools.api import ToolsAPI, ToolsAPIConfig
from ..utils import RecoverableError, CommandError, MaxIterationsError
from .session import QuerySession

logger = getLogger(__name__)

class Assistant:

    def __init__(
            self,
            instructions: str,
            repo_path: Path,
            config: Config
    ) -> None:

        self.tools_api = ToolsAPI(
            config=ToolsAPIConfig(
                repo_path=repo_path,
                blocked_files=config.blocked_files,
                blocked_dirs=config.blocked_dirs
            )
        )

        self.memory = ActiveMemory(
            tools_api=self.tools_api,
            short_memory=ShortMemory(),
            long_memory=LongMemory()
        )

        self.logger = Logger(
            log_path=config.log_path
        )

        self.llm = create_llm(
            instructions=instructions,
            config=config
        )

        self.instructions = instructions
        self.repo_path = repo_path
        self.config = config

        self.mapping = self._get_command_function_mapping()
        print("Assistant initialized")

    @staticmethod
    def get_approval(message: str) -> bool:
        approval = input(f"{message} [y/N]: ")
        return approval.strip().lower() == "y"

    def _run_agent_loop(
            self,
            session: QuerySession,
            api: ToolsAPI
    ) -> str:

        tool_schemas = api.schemas()
        initial_memory = session.memory_log()

        response = self.llm.generate(
            context=session.context(),
            tools=tool_schemas,
        )

        for i in range(self.config.max_iters):
            usage = self.llm.usage(response=response)
            tool_calls = self.llm.tool_call_contract(response)

            if not tool_calls:
                output_text = self.llm.output_text(response)

                session.add_llm_call(
                    LLMFinalCallLog(
                        initial_memory=initial_memory,
                        usage=usage,
                        response=output_text,
                    )
                )

                session.complete_loop(output_text)
                return output_text

            call_log = LLMToolEventLog(
                usage=usage,
                initial_memory=initial_memory,
            )
            session.add_llm_call(call_log)

            if i == self.config.max_iters - 1:
                raise MaxIterationsError(
                    f"Maximum iteration limit reached: "
                    f"{self.config.max_iters}"
                )

            for call in tool_calls:
                tool_response = api.execute_call(
                    call=call,
                    approval_handler=self.get_approval
                )

                if tool_response.is_fail():
                    event = ToolEvent(
                        call=call,
                        output=tool_response.output,
                    )
                else:
                    event = ToolEvent(
                        call=call,
                        output=tool_response.output,
                        update_when=tool_response.update_when,
                        update_scope=tool_response.update_scope,
                    )

                call_log.events.append(event.to_log())
                session.add_event(event)

            final_memory = session.memory_log()
            call_log.final_memory = final_memory
            initial_memory = final_memory

            response = self.llm.generate(
                context=session.context(),
                tools=tool_schemas,
            )

    def _run_query(self, query: str) -> str:
        try:
            with QuerySession(
                    query=query,
                    memory=self.memory,
                    query_logger=self.logger,
            ) as session:
                with self.tools_api as api:
                    return self._run_agent_loop(session, api)

        except Exception:
            try:
                self.logger.log()
            except Exception:
                logger.exception(
                    "Failed to persist query log after query failure."
                )

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
                command, args = self._parse_command(query)

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
            f"Cache write tokens: {usage.cache_write_tokens}"
        )

    @_command()
    def model(self) -> str:
        """
        Shows current model if no model name is provided.
        Changes model if model name is provided.
        """

        return (
            f"Current model: {self.llm.model_data.id}"
        )

    @_command()
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

    @_command()
    def reasoning_level(self) -> str:
        """
        Shows current reasoning level if no reasoning level is provided.
        Changes reasoning level if reasoning level is provided.
        """

        return (
            f"Current config reasoning: {self.config.reasoning}\n"
            f"Current effective reasoning: {self.llm.reasoning}"
        )

    @_command()
    def reasoning_levels(self) -> str:
        """
        Shows valid reasoning levels.
        """

        levels = self.llm.model_data.reasoning.levels
        if levels:
            return f"Valid reasoning levels: {', '.join(levels)}."
        else:
            return f"No reasoning levels configured for model {self.llm.model_data.id}."

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
