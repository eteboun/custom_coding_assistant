from ..tools.context import ToolEvent, ToolOutput
from ..tools.api import ToolsAPI, ApprovalHandler

from ..runtime.logger import LLMFinalCallLog, LLMToolEventLog
from ..runtime.session import QuerySession

from ..utils import MaxIterationsError
from ..providers.base import BaseLLM

from typing import Literal
from abc import ABC, abstractmethod

class Architecture(ABC):
    @abstractmethod
    def run(
            self,
            approval_handler: ApprovalHandler,
            llm: BaseLLM,
            session: QuerySession,
            api: ToolsAPI,
            max_iters: int
    ) -> str:
        ...

ArchitectureName = Literal[
    "prev_id", "persistent_memory", "active_memory"
]

class ActiveMemoryArchitecture(Architecture):
    def run(
            self,
            approval_handler: ApprovalHandler,
            llm: BaseLLM,
            session: QuerySession,
            api: ToolsAPI,
            max_iters: int
    ) -> str:

        tool_schemas = api.schemas()
        initial_memory = session.memory.to_log()

        response = llm.generate(
            input_=session.context(),
            tools=tool_schemas,
        )

        for i in range(max_iters):
            usage = llm.usage(response=response)
            tool_calls = llm.tool_call_contract(response)

            if not tool_calls:
                output_text = llm.output_text(response)

                llm_call = LLMFinalCallLog(
                        usage=usage,
                        response=output_text
                    )
                llm_call.initial_memory = initial_memory

                session.add_llm_call(llm_call)

                session.complete_loop(output_text)
                return output_text

            call_log = LLMToolEventLog(
                usage=usage
            )
            call_log.initial_memory = initial_memory

            session.add_llm_call(call_log)

            if i == max_iters - 1:
                raise MaxIterationsError(
                    f"Maximum iteration limit reached: "
                    f"{max_iters}"
                )

            for call in tool_calls:
                tool_response = api.execute_call(
                    call=call,
                    approval_handler=approval_handler
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

            final_memory = session.memory.to_log()
            call_log.final_memory = final_memory
            initial_memory = final_memory

            response = llm.generate(
                input_=session.context(),
                tools=tool_schemas,
            )

class PersistentMemoryArchitecture(Architecture):
    def __init__(self) -> None:
        self.id_ = None

    def run(
            self,
            approval_handler: ApprovalHandler,
            llm: BaseLLM,
            session: QuerySession,
            api: ToolsAPI,
            max_iters: int
    ) -> str:

        tool_schemas = api.schemas()
        initial_memory = session.memory.to_log()

        response = llm.generate(
            input_=session.context(),
            tools=tool_schemas
        )
        self.id_ = llm.response_id(response)

        for i in range(max_iters):
            usage = llm.usage(response=response)
            tool_calls = llm.tool_call_contract(response)

            if not tool_calls:
                output_text = llm.output_text(response)

                llm_call = LLMFinalCallLog(
                        usage=usage,
                        response=output_text
                    )
                llm_call.initial_memory = initial_memory

                session.add_llm_call(llm_call)

                session.complete_loop(output_text)
                return output_text

            call_log = LLMToolEventLog(
                usage=usage
            )
            call_log.initial_memory = initial_memory

            session.add_llm_call(call_log)

            if i == max_iters - 1:
                raise MaxIterationsError(
                    f"Maximum iteration limit reached: "
                    f"{max_iters}"
                )

            outputs: list[ToolOutput] = []
            for call in tool_calls:
                tool_response = api.execute_call(
                    call=call,
                    approval_handler=approval_handler
                )

                outputs.append(
                    tool_response.output
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

                call_log.events.append(
                    event.to_log()
                )
                session.add_event(event)

            final_memory = session.memory.to_log()
            call_log.final_memory = final_memory
            initial_memory = final_memory

            response = llm.generate(
                input_=[
                    (call, output)
                    for call, output in zip(tool_calls, outputs)
                ],
                tools=tool_schemas,
                prev_id=self.id_
            )
            self.id_ = llm.response_id(response)

class PrevIdArchitecture(Architecture):
    def __init__(self) -> None:
        self.id_ = None

    def run(
            self,
            approval_handler: ApprovalHandler,
            llm: BaseLLM,
            session: QuerySession,
            api: ToolsAPI,
            max_iters: int
    ) -> str:

        tool_schemas = api.schemas()

        response = llm.generate(
            input_=session.context(),
            tools=tool_schemas,
            prev_id=self.id_
        )
        self.id_ = llm.response_id(response)

        for i in range(max_iters):
            usage = llm.usage(response=response)
            tool_calls = llm.tool_call_contract(response)

            if not tool_calls:
                output_text = llm.output_text(response)

                session.add_llm_call(
                    LLMFinalCallLog(
                        usage=usage,
                        response=output_text
                    )
                )

                session.complete_loop(output_text)
                return output_text

            call_log = LLMToolEventLog(
                usage=usage
            )
            session.add_llm_call(call_log)

            if i == max_iters - 1:
                raise MaxIterationsError(
                    f"Maximum iteration limit reached: "
                    f"{max_iters}"
                )

            outputs: list[ToolOutput] = []
            for call in tool_calls:
                tool_response = api.execute_call(
                    call=call,
                    approval_handler=approval_handler
                )

                outputs.append(
                    tool_response.output
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

            response = llm.generate(
                input_=[
                    (call, output)
                    for call, output in zip(tool_calls, outputs)
                ],
                tools=tool_schemas,
                prev_id=self.id_
            )
            self.id_ = llm.response_id(response)
