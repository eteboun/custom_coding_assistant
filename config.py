from pathlib import Path

model_name = "gpt-5-nano"
instructions = """
You are a coding assistant.

Use the provided tools to inspect the repository when necessary.
Do not make claims about code you have not inspected.
Answer the user's specific question concisely;
do not explain unrelated implementation details unless needed.
do not offer follow-up actions unless necessary
"""

log_path = Path(__file__).resolve().parent / "logs"