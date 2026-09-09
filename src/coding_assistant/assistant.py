from openai import OpenAI
from openai.types.responses import Response
from openai.types.shared_params import Reasoning
from dotenv import load_dotenv

from .tools.content import Tools, ToolCall, ToolOutput
from .logger import SessionLogger, ToolCallLog, LLMToolCallLog, LLMFinalCallLog, LLMCallLog
from .config import Config, instructions

import json
from pathlib import Path
from functools import wraps

load_dotenv()

class Assistant:

    def __init__(self, repo_path: Path, config: Config) -> None:
        self.repo_path = repo_path
        self.config = config

        self.instructions = instructions

        self.tools = Tools(
            repo_path=self.repo_path,
            blocked_files=self.config.blocked_files,
            blocked_dirs=self.config.blocked_dirs
        )

        self.reasoning = Reasoning(
            effort=self.config.reasoning,
        )

        self.client = OpenAI()

    @staticmethod
    def _running(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            print("Assistant is now running...")
            return func(self, *args, **kwargs)

        return wrapper

    @staticmethod
    def _llm_call_log(
            response: Response,
            is_final: bool,
            tool_calls: list[ToolCall] | None = None,
            outputs: list[ToolOutput] | None = None
    ) -> LLMCallLog:
        usage = response.usage

        if usage is not None:
            input_tokens = usage.input_tokens
            output_tokens = usage.output_tokens
            reasoning_tokens = usage.output_tokens_details.reasoning_tokens
        else:
            input_tokens = 0
            output_tokens = 0
            reasoning_tokens = 0

        if is_final:
            return LLMFinalCallLog(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    reasoning_tokens=reasoning_tokens,
                    response=response.output_text
                )

        if tool_calls is None or outputs is None:
            raise ValueError(
                "tool_calls and outputs are required for a tool call log"
            )

        if len(tool_calls) != len(outputs):
            raise ValueError("Tool calls and outputs count mismatch")

        return LLMToolCallLog(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                reasoning_tokens=reasoning_tokens,
                tool_calls=[
                    ToolCallLog(
                        name=call.name,
                        args=call.args,
                        output=tool_output.output,
                    )
                    for call, tool_output in zip(
                        tool_calls, outputs
                    )
                ]
            )

    def _llm_initial_call(self, query: str) -> Response:
        return self.client.responses.create(
            model=self.config.model_name,
            instructions=self.instructions,
            input=query,
            tools=self.tools.datas,
            reasoning=self.reasoning
        )

    def _llm_next_call(self, input_: list[dict], prev_id: str) -> Response:
        return self.client.responses.create(
            model=self.config.model_name,
            instructions=self.instructions,
            tools=self.tools.datas,
            input=input_,
            previous_response_id=prev_id,
            reasoning=self.reasoning,
        )

    @staticmethod
    def _tool_calls(response: Response) -> list[ToolCall]:

        tool_calls: list[ToolCall] = []
        for item in response.output:
            if item.type == "function_call":
                tool_calls.append(
                    ToolCall(
                        name=item.name,
                        args=json.loads(item.arguments),
                        call_id=item.call_id
                    )
                )

        return tool_calls

    @_running
    def run(self, query: str) -> str:

        session_logger = SessionLogger(
            query=query,
            log_path=self.config.log_path
        )

        try:
            response = self._llm_initial_call(query=query)

            for _ in range(self.config.max_iters):
                tool_calls = self._tool_calls(response=response)

                if not tool_calls:
                    session_logger.add_llm_call(
                        llm_call=self._llm_call_log(
                            response=response,
                            is_final=True,
                        )
                    )
                    return response.output_text

                outputs = [
                    call.execute(tools=self.tools)
                    for call in tool_calls
                ]

                session_logger.add_llm_call(
                    llm_call=self._llm_call_log(
                        response=response,
                        is_final=False,
                        tool_calls=tool_calls,
                        outputs=outputs,
                    )
                )

                response = self._llm_next_call(
                    input_=[output.serialize() for output in outputs],
                    prev_id=response.id,
                )

            raise RuntimeError(
                f"Maximum iteration limit reached: {self.config.max_iters}"
            )

        finally:
            if session_logger.llm_calls:
                session_logger.log()