# Custom Coding Assistant

A Python command-line coding agent that works with OpenAI, Anthropic, and Google models. Give it a task in plain language, and it can inspect a repository, edit files, and execute commands through a shared tool interface.

The provider is selected automatically from the configured model. Model metadata and agent instructions live in editable files rather than being embedded in the CLI.

## Requirements

- Python **3.13 or newer**.
- An API key and model access for the provider you want to use.
- Docker installed and running if you want the agent to execute commands. File inspection and editing do not require Docker.

## Installation

From this project's root directory:

```bash
python -m venv .venv
```

Activate the environment:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install the project and its dependencies in editable mode:

```bash
python -m pip install -e .
```

This installs the `custom-assistant` command. The instructions below assume an editable installation from this checkout.

## API credentials

The CLI calls `python-dotenv` to load environment variables from a `.env` file. You can also set credentials in your shell. Set the variable for your chosen provider; you do not need keys for all three.

| Provider | Environment variable |
| --- | --- |
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| Google | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |

For example, when running from this project's root, create a `.env` file there containing your chosen key:

```dotenv
OPENAI_API_KEY=your-api-key
```

Do not commit credentials. See [Safety and execution limits](#safety-and-execution-limits) before using the agent with sensitive files.

## Configuration

The assistant reads **`assistant.json` from the current working directory**, which is also the repository it operates on. The checked-in configuration is:

```json
{
  "model_name": "gpt-6-astra",
  "reasoning": "medium",
  "max_iters": 10,
  "log_path": "./logs",
  "blocked_files": [".env"],
  "blocked_dirs": [
    ".git",
    ".venv",
    ".idea",
    "venv",
    "__pycache__",
    "logs"
  ]
}
```

| Setting | Purpose |
| --- | --- |
| `model_name` | Model key in [`models.json`](src/coding_assistant/models.json). Determines the provider. |
| `reasoning` | Reasoning level supported by that model. Omit it or use `null` to use the registry default; startup fails if a required default is missing. |
| `max_iters` | Maximum agent-loop iterations per query. Reaching the limit with pending tool calls raises an error. |
| `log_path` | Directory for session logs, resolved relative to `assistant.json`. The default `./logs` is created on startup. |
| `blocked_files` | File exclusions used by the repository file tools. |
| `blocked_dirs` | Directory exclusions used by the repository file tools. |

All settings except `reasoning` are required. For a nested `log_path`, ensure its parent directory already exists.

The model registry contains OpenAI GPT, Anthropic Claude, and Google Gemini entries, along with reasoning levels, token limits, and pricing metadata. These are local configuration entries, **not a guarantee of live API availability or current pricing**. Choose a model your provider account can access and update the registry if necessary.

To change models, edit `model_name` and select a compatible `reasoning` value, then restart the CLI. There is no interactive model-switch command.

## Usage

Run from the repository you want the agent to work on:

```bash
custom-assistant
```

Enter a request at the `>` prompt. Requests can span multiple lines; **submit an empty line to send the request**.

```text
> Explain how configuration is loaded in this project.
Focus on required settings and error handling.

```

You can also ask it to implement changes, investigate bugs, or run checks. File edits are applied directly to the working tree, so review the resulting changes.

To work on another repository, put an `assistant.json` in that repository, change into it, and run `custom-assistant` from the activated environment. Ensure your API credentials are available in the process environment or a dotenv file discoverable by `python-dotenv`.

### Interactive commands

Submit these with an empty line, just like a normal request:

| Command | Action |
| --- | --- |
| `/help` | Show command descriptions. |
| `/model` | Show the current model and configured reasoning value. |
| `/models` | List models in the local registry, grouped by provider. |
| `/reasoning_levels` | List valid reasoning levels for the current model. |
| `/tools` | List available agent tools. |
| `/usage` | Show accumulated session token usage, including reasoning and cache fields where reported. |
| `/log` | Write the current session log to a timestamped JSON file. |
| `exit` or `quit` | Exit the CLI. |

Use `/log` before exiting if you want to save a session. Logs include queries, model calls, tool arguments/results, and token usage; treat them as potentially sensitive.

## Safety and execution limits

The agent has tools to read and search files, list directories, apply patches that create/update/delete files, delete directories, and run commands. File-changing tools operate on the host repository without an interactive approval step. Use version control or a backup and review edits before committing.

Command execution uses a fresh `python:3.13-slim` Docker container with:

- The repository mounted **read-only** at `/workspace`.
- Networking disabled and a read-only root filesystem.
- A non-root user, dropped capabilities, and `no-new-privileges`.
- A 30-second subprocess timeout, 512 MB memory, one CPU, and a 64-process limit.
- A temporary writable `/tmp` filesystem.

You can fetch the image in advance:

```bash
docker pull python:3.13-slim
```

The container does not inherit your host virtual environment or installed development tools. Commands that need additional dependencies, network access, or writes to the repository may fail. This is a restricted command runner, not a fully provisioned development environment.

**The file blocklists are not a complete security boundary.** The command runner mounts the entire repository, including blocked paths, so commands may still read files excluded from the file tools. Keep secrets outside the mounted repository when possible. Prompts and tool results may be sent to the selected model provider.

## Customization

- [`assistant.json`](src/coding_assistant/assistant.json): per-repository model, reasoning, iteration, logging, and exclusion settings.
- [`src/coding_assistant/models.json`](src/coding_assistant/models.json): model catalog and metadata.
- [`src/coding_assistant/instructions.md`](src/coding_assistant/instructions.md): agent instructions loaded at startup; edit and restart to apply changes.
- [`src/coding_assistant/providers/`](src/coding_assistant/providers/): provider adapters and the shared agent loop.
- [`src/coding_assistant/tools/`](src/coding_assistant/tools/): tool definitions, path handling, and patch support.