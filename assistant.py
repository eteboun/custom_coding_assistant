from openai import OpenAI
from openai.types.responses import Response
from dotenv import load_dotenv

from config import model_name, instructions
from tools.content import FunctionToolCall, FunctionToolNames
from tools.obj import available_tools
from logger import SessionLogger, FunctionToolCallLog, LLMToolCallLog, LLMFinalCallLog

import json

load_dotenv()

class Assistant:

    def __init__(self,
                 model_name: str,
                 instructions: str,
                 tools: list,
                 max_iters: int
                 ) -> None:
        self.model_name = model_name
        self.instructions = instructions
        self.tools = tools
        self.max_iters = max_iters
        self.client = OpenAI()

    @staticmethod
    def _args_to_dict(args: str) -> dict:
        return json.loads(args)

    def _llm_initial_call(self, query: str) -> Response:
        return self.client.responses.create(
            model=self.model_name,
            instructions=self.instructions,
            input=query,
            tools=self.tools,
        )

    def _llm_next_call(self, input_: list[dict], prev_id: str) -> Response:
        return self.client.responses.create(
            model=self.model_name,
            tools=self.tools,
            input=input_,
            previous_response_id=prev_id,
        )

    def _func_tool_calls(self, response: Response) -> list[FunctionToolCall]:

        function_tool_calls: list[FunctionToolCall] = []
        for item in response.output:
            if item.type == "function_call":
                function_tool_calls.append(
                    FunctionToolCall(
                        tool=FunctionToolNames(item.name),
                        args=self._args_to_dict(item.arguments),
                        call_id=item.call_id
                    )
                )

        return function_tool_calls

    def run(self, query: str) -> str:

        session_logger = SessionLogger(query=query)

        try:
            response = self._llm_initial_call(query=query)

            for _ in range(self.max_iters):
                function_tool_calls = self._func_tool_calls(
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

                if not function_tool_calls:
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
                            FunctionToolCallLog(
                                name=call.tool,
                                args=call.args
                            )
                            for call in function_tool_calls
                        ]
                    )
                )

                serialized_outputs = [
                    tool.execute().serialize()
                    for tool in function_tool_calls
                ]

                response = self.client.responses.create(
                    model=self.model_name,
                    tools=self.tools,
                    input=serialized_outputs,
                    previous_response_id=response.id,
                )

            raise RuntimeError(
                f"Maximum iteration limit reached: {self.max_iters}"
            )

        finally:
            if session_logger.llm_calls:
                session_logger.log()

assistant = Assistant(
    model_name=model_name,
    instructions=instructions,
    tools=available_tools,
    max_iters=10
)

print(assistant.run(query="Assistant.run nedir?"))
