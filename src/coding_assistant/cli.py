import sys
import logging

from pathlib import Path

from coding_assistant.assistant.assistant import Assistant
from coding_assistant.assistant.config import Config, instructions, config_file

from dotenv import load_dotenv


def main():
    load_dotenv()
    logger = logging.getLogger(__name__)

    repo_path = Path.cwd()

    try:
        config = Config.from_json(
            json_path=config_file,
            repo_path=repo_path
        )

        assistant_ = Assistant(
            repo_path=repo_path,
            config=config,
            instructions=instructions
        )

    except Exception:
        logger.exception("Internal error")
        print("Internal error.", file=sys.stderr)
        sys.exit(1)

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
