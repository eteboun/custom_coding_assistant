from pathlib import Path

from .ai.config import Config
from .ai.llm import create_llm

class Assistant:

    def __init__(
            self,
            instructions: str,
            repo_path: Path,
            config: Config
    ) -> None:
        self.llm = create_llm(
            instructions=instructions,
            repo_path=repo_path,
            config=config
        )

        print("Assistant initialized")

    def query(self, query: str) -> str:
        match query.strip():
            case "/usage":
                return self._command_usage()

            case "/model":
                return self._command_model()

            case _:
                return self.llm.run(query)

    def _command_usage(self) -> str:
        usage = self.llm.logger.total_usage()

        return (
            f"Input tokens: {usage.input_tokens}\n"
            f"Output tokens: {usage.output_tokens}\n"
            f"Reasoning tokens: {usage.reasoning_tokens}\n"
            f"Total tokens: {usage.total_tokens}\n"
            f"Cached input tokens: {usage.cached_input_tokens}\n"
            f"Cache write tokens: {usage.cache_write_tokens}\n"
        )

    def _command_model(self) -> str:
        return (
            f"Current model: {self.llm.model_data.id}\n"
            f"Reasoning: {self.llm.config.reasoning}"
        )
