from openai import OpenAI
from openai.types.responses import Response
from openai.types.shared_params import Reasoning
from dotenv import load_dotenv

from tools.content import Tools, ToolCall
from logger import SessionLogger, ToolCallLog, LLMToolCallLog, LLMFinalCallLog
from config import Config, instructions

import json

load_dotenv()

class Assistant:

    def __init__(self, config_path: str) -> None:
        self.config = Config.from_json(config_path)
        self.instructions = instructions

        self.tools = Tools(repo_path=self.config.repo_path)

        self.reasoning = Reasoning(
            effort=self.config.reasoning,
        )

        self.client = OpenAI()

    @staticmethod
    def _args_to_dict(args: str) -> dict:
        return json.loads(args)

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
                        args=self._args_to_dict(item.arguments),
                        call_id=item.call_id
                    )
                )

        return tool_calls

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

                session_logger.add_llm_call(
                    LLMToolCallLog(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        reasoning_tokens=reasoning_tokens,
                        tool_calls=[
                            ToolCallLog(
                                name=call.name,
                                args=call.args
                            )
                            for call in tool_calls
                        ]
                    )
                )

                serialized_outputs = [
                    tool.execute(tools=self.tools).serialize()
                    for tool in tool_calls
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