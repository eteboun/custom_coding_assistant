from openai import OpenAI
from openai.types.responses import Response
from openai.types.shared_params import Reasoning
from dotenv import load_dotenv

from .tools.content import Tools, ToolCall
from .logger import SessionLogger, ToolCallLog, LLMToolCallLog, LLMFinalCallLog
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

    def _tool_calls(self, response: Response) -> list[ToolCall]:

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
                tool_calls = self._tool_calls(
                    response=response
                )

                usage = response.usage

                if usage is not None:
                    input_tokens = usage.input_tokens
                    raw_output_tokens = usage.output_tokens
                    reasoning_tokens = usage.output_tokens_details.reasoning_tokens
                else:
                    input_tokens = 0
                    raw_output_tokens = 0
                    reasoning_tokens = 0

                output_tokens = raw_output_tokens - reasoning_tokens

                if not tool_calls:
                    session_logger.add_llm_call(
                        LLMFinalCallLog(
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            reasoning_tokens=reasoning_tokens,
                            response=response.output_text
                        )
                    )
                    return response.output_text

                outputs = [
                    call.execute(tools=self.tools)
                    for call in tool_calls
                ]

                session_logger.add_llm_call(
                    LLMToolCallLog(
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
                )

                serialized_outputs = [
                    output.serialize()
                    for output in outputs
                ]

                response = self.client.responses.create(
                    model=self.config.model_name,
                    tools=self.tools.datas,
                    input=serialized_outputs,
                    previous_response_id=response.id,
                )

            raise RuntimeError(
                f"Maximum iteration limit reached: {self.config.max_iters}"
            )

        finally:
            if session_logger.llm_calls:
                session_logger.log()