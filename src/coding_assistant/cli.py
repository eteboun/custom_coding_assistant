from pathlib import Path

from .assistant import Assistant
from .config import Config, config_filename

def main():
    repo_path = Path.cwd()
    config_path = repo_path / config_filename

    config = Config.from_json(config_path.as_posix())
    assistant_ = Assistant(repo_path=repo_path, config=config)

    while True:
        try:
            query = input("> ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not query:
            continue

        if query in {"exit", "quit"}:
            break

        return assistant_.run(query=query)