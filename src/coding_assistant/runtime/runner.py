from ..memory import Memory
from ..providers.base import BaseLLM
from ..tools.api import ApprovalHandler, ToolsAPI
from ..tools.context import ToolEvent
from ..utils import MaxIterationsError
from .logger import Logger, LLMCallLog, LLMFinalCallLog, LLMToolEventLog
from .session import QuerySession


def run(
    query: str,
    *,
    llm: BaseLLM,
    memory: Memory,
    tools_api: ToolsAPI,
    logger: Logger,
    approval_handler: ApprovalHandler | None = None,
) -> str:

    with QuerySession(query, logger, memory) as session:
        with tools_api:
            schemas = tools_api.schemas()

            for _ in range(llm.max_iters):
                initial_memory = memory.to_log()
                response = llm.generate(session.context(), schemas)
                usage = llm.usage(response)
                memory.context_size = usage.input_tokens
                memory.context_size_is_estimate = False
                try:
                    text = llm.output_text(response)
                    calls = llm.tool_call_contract(response)
                except Exception:
                    # Keep billed usage even if the response cannot be decoded.
                    call_log = LLMCallLog(usage=usage)
                    call_log.memory = initial_memory
                    session.add_llm_call(call_log)
                    raise

                if not calls:
                    final_log = LLMFinalCallLog(usage=usage, response=text)
                    final_log.memory = initial_memory
                    session.add_llm_call(final_log)
                    session.complete_loop(text)
                    return text

                tool_log = LLMToolEventLog(usage=usage)
                tool_log.memory = initial_memory
                session.add_llm_call(tool_log)
                if text:
                    memory.add_output_text(text)

                for call in calls:
                    result = tools_api.execute_call(call, approval_handler=approval_handler)
                    event = ToolEvent(call=call, output=result.output)
                    session.add_event(event)
                    tool_log.events.append(event.to_log())

            raise MaxIterationsError(
                f'Maximum iterations reached ({llm.max_iters}); the task may be incomplete.'
            )
