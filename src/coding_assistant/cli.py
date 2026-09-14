from pathlib import Path

from .assistant import Assistant
from .config import Config, config_filename, instructions

from dotenv import load_dotenv

def main():
    load_dotenv()

    repo_path = Path.cwd()
    config_path = repo_path / config_filename

    config = Config.from_json(config_path.as_posix())
    assistant_ = Assistant(
        repo_path=repo_path,
        config=config,
        instructions=instructions
    )

    while True:
        lines = []

        line = input("> ")
        if line:
            lines.append(line)

        while line:
            line = input()
            if line:
                lines.append(line)

        query = "\n".join(lines)

        if not query:
            continue

        if query in {"exit", "quit"}:
            break

        print(assistant_.query(query=query))