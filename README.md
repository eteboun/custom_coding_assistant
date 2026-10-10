# Custom Coding Assistant

A coding assistant that reads and searches a repository, applies patches, and runs commands in Docker. The application manages an ordered memory stream and replaces older query transcripts with structured query records when context grows.

Its central features are **deterministic memory tracing** and **deterministic compression**. Code defines how events enter memory and which fields survive compression. Compression does not ask a model to generate a summary and does not make an additional model API call.

Deterministic here describes the application's bookkeeping and representation changes. Model responses, tool choices, and external command results can still vary. Given the same events and query records, the memory and compression rules produce the same representation.

## Requirements and installation

- Python **3.13 or newer**.
- **ripgrep** (`rg`) available on the host's `PATH` for file and content searches.
- Docker CLI and a running Docker engine. On Windows, use Linux containers.
- API access to the configured model. **OpenAI** is the currently implemented provider.

Development installation in PowerShell:

```powershell
python -m venv .venv
.venv/Scripts/Activate.ps1
python -m pip install -e .
$env:OPENAI_API_KEY = "your-api-key"
```

The CLI also loads a `.env` file through `python-dotenv`. The default configuration blocks agent tools from accessing `.env`.

Start Docker and prepare the default sandbox image:

```powershell
docker pull python:3.13-slim
```

Launch the assistant from the repository you want it to work on:

```powershell
cd C:/path/to/target-repository
custom-assistant
```

The **current working directory** becomes the repository root. It does not have to be the assistant's installation directory.

Queries can contain multiple lines. Submit a query by entering a blank line:

```text
> Fix the validation bug in src/parser.py and run the relevant tests.

```

Submit slash commands the same way. Use `exit` or `quit` to leave. When command execution requests approval, only `y` grants it.

The sandbox starts and stops for each normal query, including queries that only read files. Docker is therefore required for normal queries. Slash commands do not start a model loop or sandbox.

## Configuration

Packaged defaults live in `src/coding_assistant/resources/assistant.json`:

```json
{
  "model_name": "gpt-5.6-sol",
  "reasoning": "medium",
  "max_iters": 30,
  "log_path": "./logs",
  "blocked_files": [".env"],
  "blocked_dirs": [
    ".git", ".venv", ".idea", "venv", "__pycache__", "logs"
  ]
}
```

| Field | Meaning |
| --- | --- |
| `model_name` | Model key in the local catalog. |
| `reasoning` | A supported reasoning level, or `null` for models without reasoning support. |
| `max_iters` | Maximum model calls per query, not the number of tool calls within a response. |
| `log_path` | Directory used by `/log`; resolved relative to the target repository in the CLI. |
| `blocked_files` | Repository-relative files excluded from tool access. |
| `blocked_dirs` | Repository-relative directories and their descendants excluded from tool access. |

`resources/models.json` contains model IDs, context windows, reasoning settings, and pricing. This is a local catalog, not live provider discovery. `resources/instructions.md` contains the agent instructions.

The CLI currently has no `--config` option or automatic target-repository configuration discovery. Edit the packaged resources in an editable development installation, or construct a `Config` in Python. Context thresholds are class attributes on `Assistant`, not JSON configuration fields.

## Tools

The model receives JSON schemas for the available tools. Arguments are validated against those schemas before execution. Unknown tools, invalid arguments, and backend usage errors become `error` tool outputs. Rejected approval requests become `denied` outputs.

| Tool | Arguments | Behavior |
| --- | --- | --- |
| `read_file` | `path`, optional `start_line`, `end_line` | Reads a known text file. Line numbers are 1-based; the end line is inclusive. |
| `list_directory` | `path` | Lists immediate directory contents. Use `.` for the repository root. |
| `search_files` | Optional `pattern`, `max_results=100` | Finds file paths using ripgrep. Example globs: `*.py`, `src/**/*.ts`. |
| `search_text` | `query`, `context_lines=2`, `regex=false`, `max_output_lines=100` | Searches file contents for literal text or a ripgrep regular expression. |
| `repo_tree` | None | Shows repository structure without reading contents, up to depth 4. |
| `apply_patch` | `patch` | Adds, updates, or deletes files and returns actual mutations. |
| `delete_directory` | `path` | Deletes an empty directory. |
| `run_command` | `command` | Runs a shell command in Docker after user approval. |

There is no `change_summary` argument or model-generated mutation summary. Mutation tracing relies on changes reported by the backend.

File operations run on the host through the workspace backend. Commands run through the Docker backend. Workspace path checks reject access outside the repository and access to blocked paths, checking both resolved and lexical paths. ripgrep searches also follow ripgrep's default ignore behavior.

### Patch format

`apply_patch` accepts the following operations:

```text
*** Begin Patch
*** Update File: src/example.py
@@
 unchanged context
-old line
+new line
*** Add File: src/new_file.py
+print("hello")
*** Delete File: src/obsolete.py
*** End Patch
```

Update hunks must match exactly one location in the original file and must not overlap. Add File content must use `+`-prefixed lines. Delete File operations must not include file content. Move/rename metadata is not supported.

### Mutation tracing

A mutation records a changed path and operation:

```json
{"path": "src/example.py", "type": "update"}
```

Operations are `add`, `update`, and `delete`. These records do not contain full file contents, diffs, or semantic explanations.

The query session saves a structured mutation event only when a tool output contains actual mutations. A test command that makes no repository changes therefore creates a raw tool event but no mutation event in the query record.

For each retained mutation event, the query record stores the tool name, mutation list, and outcome status/message. The user query and final response provide any surrounding explanation that survives compression.

### Sandbox behavior

| Setting | Default |
| --- | --- |
| Image | `python:3.13-slim` |
| Working directory | `/workspace` |
| Network | Disabled with `--network none` |
| Memory limit | `512m` |
| CPU limit | `1.0` |
| PID limit | `64` |
| Command timeout | 30 seconds |

The repository is mounted writable at `/workspace`; command changes affect the host repository. Existing blocked paths are masked with empty, read-only mounts. The default image does not include every target project's dependencies, and network access is disabled inside the container.

Normally completed commands compare filesystem snapshots before and after execution. Files are tracked by SHA-256, symlinks by their targets, and directories by their presence. Blocked paths are excluded. Outputs contain `exit_code`, `stdout`, `stderr`, and detected mutations.

A nonzero exit code does not necessarily produce tool status `error`: the shell can execute successfully while the command fails. Inspect `exit_code` to assess test or build success.

On timeout, the container is removed and recreated to stop the command from continuing in the background. Repository changes are not rolled back. The current timeout path returns an error without the normal snapshot mutation list, so changes made before timeout can be absent from the query record.

## Deterministic memory tracing

`Memory` maintains two separate lists:

- **`elements`**: The ordered stream used to construct the next model input.
- **`query_records`**: Compact records finalized when query sessions end. They do not enter context separately until compression.

| Element | Content | Added when |
| --- | --- | --- |
| `QueryElement` | User query | The query session starts. |
| `OutputTextElement` | Assistant text | A response with tool calls also contains text, or the session ends with a final response. |
| `ToolEventElement` | Tool call and its output together | Tool execution returns an output. |
| `QueryRecord` | Compact query history | Compression replaces historical raw elements. |

**Tool event insertion is atomic at the memory representation level.** A call is not appended first and its output appended later as a separate element. A complete `ToolEvent(call, output)` is constructed and inserted once. This does not provide a filesystem transaction or crash recovery guarantee.

Multiple tool calls in one response execute sequentially, and their complete events are inserted in that order. Any accompanying assistant text is inserted before those events.

```text
QueryElement(Q1)
OutputTextElement("Inspecting the relevant file.")
ToolEventElement(read_file call + output)
ToolEventElement(apply_patch call + output)
ToolEventElement(run_command call + output)
OutputTextElement(Q1 final response)
QueryElement(Q2)
...
```

For each API call, current elements are serialized through `to_context()` as JSON inside `<memory>...</memory>`. The application sends its own context on every call instead of continuing through a previous provider response ID. Instructions and tool schemas are also supplied to the provider.

Log and context representations can differ. Tool calls contain `name` and `args` in both. Tool outputs expose status, content, message, and mutations in context; logs also include the `files` field.

### Query sessions and completion

`QuerySession` tracks the query's starting memory index and collects structured mutation events. A response without tool calls completes the loop. Loop completion is not an independent verification that the requested task is correct.

When the session closes, its finalized `QueryRecord` is appended to `memory.query_records`. Its context representation looks like this:

```json
{
  "type": "query_record",
  "query": "Fix parser validation and run the tests.",
  "loop_completed": true,
  "stop_reason": null,
  "final_response": "Validation updated; the relevant tests passed.",
  "mutation_events": [
    {
      "name": "apply_patch",
      "mutations": [{"path": "src/parser.py", "type": "update"}],
      "outcome": {"status": "success", "message": null}
    }
  ]
}
```

`QueryRecord.to_log()` contains these record fields without the context discriminator `type`.

When `max_iters` is exhausted, tool calls from the last iteration have already executed and their events have been stored. The record has `loop_completed=false`, `stop_reason="max_iterations"`, and `final_response=null` if no final response was produced. Other session exceptions produce `stop_reason="error"`.

Max iterations does not clear memory or undo repository changes. The user can continue with another query. Raw events remain available before compression; after compression, incomplete status and detected mutation events remain in the record. Not every unexpected exception is treated as a recoverable CLI error.

## Deterministic compression

Compression changes the representation of history rather than asking a model to summarize the transcript:

```python
memory.elements = [*memory.query_records, *active_elements]
```

Manual `/compress` runs between queries and does not have active elements to retain. Historical raw elements are replaced by query records in their original order. Records are collected during execution, so compression makes no additional API call and has no separate model summarization cost.

### What survives compression

| Retained | Removed from historical model context |
| --- | --- |
| User query | Detailed file reads and search results |
| Final response | Intermediate assistant text |
| Completion status and stop reason | Tool arguments and full patches |
| Detected mutation paths/operations, tool name, and outcome | Command stdout/stderr and detailed test reports |

Compression is **lossy**. Read-only findings survive only if captured in the final response. Mutation events preserve detected filesystem changes, not the exact edits or their rationale. There is no separate semantic summary field.

Query records are not recursively summarized, dropped, or forced into a fixed token budget. Recompressing the same records produces the same element representation, but accumulated records and long final responses can still grow. Compression does not guarantee a particular size reduction or final percentage.

### Compression during an active query

Automatic compression runs **before** a model call. Everything from the session's starting memory index onward belongs to the active query and is retained in its raw form:

```text
Before:
[Q1 raw events] [Q2 raw events] [Q3 active query and completed events]

After:
[Q1 record] [Q2 record] [Q3 active query and completed events]
```

The active query is not replaced with an incomplete record mid-loop. Its record is finalized only when the session closes. The model can therefore continue using all completed tool results and intermediate text from the current task. The session's memory index is adjusted after compression.

Automatic compression requires at least one historical element that is not already a `QueryRecord`. It does not repeatedly compress history that consists entirely of records, and it does not shrink a first query that grows large by itself.

The assistant prints a compression notification, before/after context information, and the number of retained active elements. Automatic compression measurements are also stored in the query log.

## Context measurement and thresholds

Before every model call, and whenever `/context` is invoked, the assistant computes:

```text
prefix = instructions + newline + serialized provider tool schemas + newline
estimated_tokens = provider.token_count(prefix + memory.format_context())
usage_percent = estimated_tokens / model.context_window * 100
```

Each provider implements `token_count(text) -> int`. The OpenAI implementation uses `tiktoken.encoding_for_model()`, falling back to `o200k_base` when the model is absent from the tokenizer mapping. Future providers can use their own tokenizers.

This is an **estimate**, since it does not reproduce the provider's exact message/protocol overhead. After an API response, memory's context counter is updated with reported `input_tokens`. The next pre-call check or `/context` recomputes the current local estimate. Reported API input tokens describe the last request and exclude events added after that request.

| Threshold | Condition | Action |
| --- | --- | --- |
| Manual compression: **50%** | Estimated usage `>= 50%` | `/compress` proceeds. Below it, compression fails without changing the elements. |
| Query-entry warning: **85%** | Stored context usage `> 85%` | Suggests `/compress` before continuing the new normal query. |
| Automatic compression: **90%** | Pre-call estimate `> 90%` with uncompressed history | Replaces history with records while preserving the active query. |
| Post-compression target: **30%** | Projected compressed usage `> 30%` | Suggests task division or a larger-context model; compression and the run continue. |
| Model-switch limit: **100%** | Candidate model estimate `> 100%` | Blocks the switch and suggests `/compress` using the current model. |

Boundary behavior matters: exactly 50% permits manual compression; exactly 85% or 90% does not trigger the corresponding warning or automatic action; exactly 30% does not trigger the preview warning; exactly 100% does not block a model switch.

The 85% warning uses the stored counter before the new query is inserted. That may be the last API input measurement or an earlier local estimate. The current estimate is recomputed after query insertion before each API call.

The 30% target is **advisory**, not a stop condition. The compressed representation is measured before it is applied. If it remains above the target, the assistant prints recommendations and proceeds. A larger context window does not reduce the input token count; changing models can affect prompt-cache reuse and may increase cost.

There is currently no general hard context-limit check for normal API calls and no reserved output/reasoning token budget. If there is no compressible history, or compression is insufficient, the call can still proceed and encounter a provider limit error. The 100% guard specifically applies to `/model` changes.

## CLI commands

| Command | Behavior |
| --- | --- |
| `/help` | Shows command descriptions. |
| `/context` | Shows the current local token estimate, context window, and usage percentage. |
| `/compress` | Replaces historical memory with query records, subject to the 50% minimum. |
| `/model` | Shows the current model ID. |
| `/model <model_name>` | Switches to a catalog model while preserving memory. |
| `/reasoning` | Shows configured and effective reasoning; accepts no argument. |
| `/usage` | Shows accumulated input/output/total, reasoning/cache tokens, and calculated USD cost. |
| `/log` | Writes accumulated query logs to a JSON file. |

There is no `/compression` alias. Slash commands do not create query records or normal memory elements. Unknown commands and invalid arguments return an error message.

### Model switching

`/model <model_name>` resolves the candidate from the local catalog and constructs its provider instance. It measures existing memory using the candidate tokenizer, tool schemas, and context window. Preparation does not make a model API call.

- Unknown models, initialization failures, or token-count failures retain the current model.
- An estimate above 100% blocks the switch. Run `/compress` with the current model and retry; compression does not guarantee that the candidate will fit.
- Estimates between 90% and 100% permit switching. The next query's pre-call check reevaluates automatic compression conditions.
- Memory elements and query records are provider-independent and are retained without reconstruction.

Reasoning selection follows this order:

1. Preserve the current effective level if the new model supports it.
2. Otherwise use the new model's default, if defined.
3. Otherwise choose its minimum supported level in this order: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`.
4. For models without reasoning support, use Python `None` and omit the reasoning parameter. This differs from the string reasoning level `"none"`.

Switching updates in-process configuration and logger model metadata. It does not rewrite the packaged configuration file.

## Logs and traceability

`/log` writes accumulated in-memory logs to a timestamped JSON file in the configured directory. There is no automatic disk write or session restoration from logs.

Each query log contains:

- Query text and the model ID used for that query.
- A memory snapshot **before each model call**.
- Per-call token usage and calculated cost.
- Tool call/output events or the final response.
- Automatic compression measurements: before/after token counts, estimate flags, and retained active element count.
- One query-level `final_memory`, elapsed time, and errors.

`final_memory` is not duplicated in subordinate model-call records. Compression reduces model context but does not clear historical tool logs. Manual compression does not create a separate query log event.

These snapshots support inspection of the application's memory flow. They are not an exact archive of provider HTTP requests/responses or an automatic replay/restore mechanism. After a model switch, earlier queries keep their own model IDs; the top-level model ID identifies the current model.

Costs are calculated from API usage and the local catalog's pricing rules. `/usage` reports accumulated query usage, while `/context` estimates current context occupancy. Keep the catalog accurate when comparing estimates with billing.

## Python usage

```python
from pathlib import Path

from coding_assistant.assistant import Assistant
from coding_assistant.config import Config
from coding_assistant.memory import Memory
from coding_assistant.resources import config_file, instructions

repo_path = Path("C:/path/to/target-repository").resolve()
config = Config.model_validate_json(
    config_file.read_text(encoding="utf-8"),
    context={"repo_path": repo_path},
)

assistant = Assistant(
    instructions=instructions,
    repo_path=repo_path,
    config=config,
    memory=Memory(),
)

print(assistant.query("Inspect the parser and fix empty-input handling."))
print(assistant.query("/context"))
print(assistant.query("/log"))
```

Set the API key in the environment beforehand or call `dotenv.load_dotenv()` yourself; `.env` loading is part of the CLI. The default command approval handler is interactive. The lower-level `runtime.runner.run()` accepts custom `approval_handler` and `before_model_call` callbacks; automatic context policy is implemented by `Assistant`.

## Project structure

```text
src/coding_assistant/
  assistant.py          # Commands, context policy, and model switching
  cli.py                # Interactive input and startup
  config.py             # Configuration validation
  context.py            # JSON/tag context formatting
  interfaces.py         # Shared log/context contracts
  errors.py             # Recoverable application errors
  mutation.py           # Changed paths and operations
  memory/
    memory.py           # Ordered elements, query records, compression
    schema.py           # MemoryElement and QueryRecord types
  runtime/
    runner.py           # Model/tool loop
    session.py          # Active query lifecycle and record collection
    logger.py           # Query and model-call logs
  tools/
    api.py              # Schema validation, approval, dispatch
    implementations.py  # Available agent tools
    context.py          # ToolCall, ToolOutput, ToolEvent
    schema.py           # Tool schemas and approval metadata
  backends/
    workspace.py        # Host repository operations
    sandbox.py          # Docker commands and snapshot tracing
    apply_patch.py      # Patch parsing and application helpers
    path_policy.py      # Blocked path policy
  providers/
    base.py             # Provider contract, including token_count
    openai.py           # OpenAI implementation
    dispatch.py         # Provider construction
  models/
    catalog.py          # Packaged catalog loading
    operations.py       # Model and reasoning resolution
    schema.py           # Model metadata and token usage
    pricing.py          # Cost calculation
  resources/
    assistant.json      # Default configuration
    models.json         # Model metadata and pricing
    instructions.md     # Agent instructions
```

New tools require schemas and backend implementations. To participate in mutation tracing, backends must return actual `Mutation` records. New providers require implementing `BaseLLM`, extending dispatch, and updating model/provider metadata.

## Current scope and development checks

Memory and query records live in process memory and are not restored automatically after restart. Compression does not modify repository files; it changes the memory representation sent in later model calls. The earlier memory architectures and benchmark system have been removed.

If the local `tests/` directory is available:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -p 'test_*.py'
```

Tests are currently kept untracked, so a clean clone is not guaranteed to include them.
