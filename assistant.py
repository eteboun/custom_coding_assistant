from openai import OpenAI
from dotenv import load_dotenv

from config import model_name, instructions
from tools import available_tools, FunctionToolCall, FunctionToolNames

import json

load_dotenv()

class Assistant:

    def __init__(self,
                 model_name: str,
                 instructions: str,
                 tools: list
                 ) -> None:
        self.model_name = model_name
        self.instructions = instructions
        self.tools = tools
        self.client = OpenAI()

    @staticmethod
    def _args_to_dict(args: str) -> dict:
        return json.loads(args)

    def run(self, query: str) -> str:

        response = self.client.responses.create(
            model=self.model_name,
            instructions=self.instructions,
            input=query,
            tools=self.tools,
        )

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

assistant = Assistant(
    model_name=model_name,
    instructions=instructions,
    tools=available_tools
)

assistant.run(query="generate_id fonksiyonu nerede çağırılıyor?")

