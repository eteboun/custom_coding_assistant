from pathlib import Path
import inspect

from .config import Config
from .logger import Logger, LLMToolEventLog, LLMFinalCallLog
from ..memory.memory import ActiveMemory, ShortMemory, LongMemory, ToolEvent

from ..models.models import models_by_provider, models_data
from ..providers.llm import create_llm

from ..models.operations import adjust_reasoning, is_valid_reasoning
from ..tools.api import ToolsAPI, ToolsAPIConfig, ToolsAPIResponse
from ..utils import RecoverableError, CommandError, ConfigError, MaxIterationsError
from .session import QuerySession

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

    def _run_query(
            self,
            query: str
    ) -> str:
        with QuerySession(
                query=query,
                memory=self.memory,
                query_logger=self.logger
        ) as session:
            with self.tools_api as api:

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

                        session.complete(output_text)
                        return output_text

                    if i == self.config.max_iters - 1:
                        raise MaxIterationsError(
                            f"Maximum iteration limit reached: "
                            f"{self.config.max_iters}"
                        )

                    tool_responses: list[ToolsAPIResponse] = []

                    for call in tool_calls:
                        if (
                                message := api.approval_message(
                                    call=call
                                )
                        ) is not None:

                            if not self.get_approval(message=message):
                                tool_responses.append(
                                    api.denied_response(call=call)
                                )
                                continue

                        tool_responses.append(
                            api.execute_call(call=call)
                        )

                    events: list[ToolEvent] = []

                    for tool_call, tool_response in zip(
                            tool_calls,
                            tool_responses,
                    ):
                        if tool_response.is_fail():
                            events.append(
                                ToolEvent(
                                    call=tool_call,
                                    output=tool_response.output,
                                )
                            )
                            continue

                        events.append(
                            ToolEvent(
                                call=tool_call,
                                output=tool_response.output,
                                update_when=tool_response.update_when,
                                update_scope=tool_response.update_scope,
                            )
                        )

                    for event in events:
                        session.add_event(event)

                    final_memory = session.memory_log()

                    session.add_llm_call(
                        LLMToolEventLog(
                            usage=usage,
                            initial_memory=initial_memory,
                            final_memory=final_memory,
                            events=[
                                event.to_log()
                                for event in events
                            ],
                        )
                    )

                    initial_memory = final_memory

                    response = self.llm.generate(
                        context=session.context(),
                        tools=tool_schemas,
                    )

    @staticmethod
    def _command(accept_args: bool = False):
        def wrapper(func):
            func.is_command = True
            func.accept_args = accept_args
            return func
        return wrapper

    def query(self, query: str) -> str:
        query = query.strip()

        try:
            if query.startswith("/"):
                command, args = self._parse_command(query)

                if command in self.mapping:
                    return self._run_command(
                        command=command,
                        args=args
                    )

                raise CommandError(
                    f"Command '{command}' not found."
                )

            return self._run_query(
                query=query
            )

        except RecoverableError as e:
            return str(e)

    def _run_command(self, command: str, args: list[str]) -> str:
        func = self.mapping[command]

        if args and not func.accept_args:
            raise CommandError(
                f"Command {command} does not accept arguments."
            )

        output = func(self, args) if func.accept_args else func(self)
        return output.strip()

    @staticmethod
    def _parse_command(query: str) -> tuple[str, list[str]]:
        entries = query.split()

        command = entries[0].removeprefix("/")
        args = entries[1:]

        return command, args

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

    @_command(accept_args=True)
    def model(self, args: list[str]) -> str:
        """
        Shows current model if no model name is provided.
        Changes model if model name is provided.
        """

        if len(args) == 0:
            return (
                f"Current model: {self.llm.model_data.id}\n"
                f"Effective reasoning: {self.llm.config.reasoning}"
            )

        if len(args) > 1:
            raise CommandError(
                "Invalid arguments."
            )

        model = args[0]
        self._change_model(model=model)

        return (
            f"Successfully changed the model to {model}.\n"
            f"Reasoning: {self.config.reasoning}"
        )

    def _change_model(self, model: str) -> None:
        model_data = models_data.models.get(model)

        if model_data is None:
            raise ConfigError(
                f"{model} is not a valid model."
            )

        reasoning = adjust_reasoning(
            model_data=model_data,
            reasoning=self.config.reasoning,
        )

        new_config = self.config.model_copy(
            update={
                "model_name": model,
                "reasoning": reasoning,
            }
        )

        new_llm = create_llm(
            instructions=self.instructions,
            config=new_config
        )

        self.config = new_config
        self.llm = new_llm

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

    @_command(accept_args=True)
    def reasoning_level(self, args: list[str]) -> str:
        """
        Shows current reasoning level if no reasoning level is provided.
        Changes reasoning level if reasoning level is provided.
        """

        if len(args) == 0:
            return (
                f"Current config reasoning: {self.config.reasoning}\n"
                f"Current effective reasoning: {self.llm.reasoning}"
            )

        if len(args) > 1:
            raise CommandError(
                "Invalid arguments."
            )

        reasoning = None if args[0] == "null" else args[0]

        if not is_valid_reasoning(
            reasoning=reasoning,
            model_data=self.llm.model_data
        ):
            raise ConfigError(
                f"Reasoning level {reasoning} is not valid."
            )

        self.llm.update_reasoning(reasoning=reasoning)
        self.config.reasoning = reasoning

        return "Successfully changed the reasoning level."

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
