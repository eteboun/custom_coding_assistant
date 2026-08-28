from openai import OpenAI
from openai.types.responses import Response
from dotenv import load_dotenv
from functools import wraps

from config import model_name, instructions
from tools import available_tools, FunctionToolCall, FunctionToolOutput, FunctionToolNames
from logger import SessionLogger, FunctionToolCallLog, LLMCallLog

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

    @staticmethod
    def _logger(func):
        @wraps(func)
        def wrapper(self, session_logger: SessionLogger, *args, **kwargs) -> Response:
            response = func(self, *args, **kwargs)

            if not isinstance(response, Response):
                raise ValueError(
                    "invalid response"
                )

            if response.usage is not None:
                session_logger.total_input_tokens += response.usage.input_tokens
                session_logger.total_output_tokens += response.usage.output_tokens

            return response
        return wrapper

    @_logger
    def _llm_first_call(self, query: str) -> Response:
        return self.client.responses.create(
            model=self.model_name,
            instructions=self.instructions,
            input=query,
            tools=self.tools,
        )

    @_logger
    def _llm_next_call(self, input_: list[dict], prev_id: str) -> Response:
        return self.client.responses.create(
            model=self.model_name,
            tools=self.tools,
            input=input_,
            previous_response_id=prev_id,
        )

    def run(self, query: str) -> str:

        session_logger = SessionLogger()
        response = self._llm_first_call(
            session_logger=session_logger,
            query=query
        )

        for _ in range(self.max_iters):

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

            if not function_tool_calls:
                return response.output_text

            function_tool_outputs: list[FunctionToolOutput] = [
                tool.execute()
                for tool in function_tool_calls
            ]

            serialized_outputs = [
                output.serialize()
                for output in function_tool_outputs
            ]

            response = self.client.responses.create(
                model=self.model_name,
                tools=self.tools,
                input=serialized_outputs,
                previous_response_id=response.id,
            )

        return "reached loop limit."

assistant = Assistant(
    model_name=model_name,
    instructions=instructions,
    tools=available_tools,
    max_iters=10
)

print(assistant.run(query="_resolve_path fonksiyonu nerede çağırılıyor?"))

