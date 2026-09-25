from dataclasses import dataclass
from pathlib import Path

from .context import Operation, ToolUsageError, LearningMetadata

@dataclass(frozen=True)
class FilePatch:
    operation: Operation
    path: str
    lines: list[str]

@dataclass(frozen=True)
class Hunk:
    start: int
    end: int
    new_text: str


def _parse_patch(patch: str) -> list[FilePatch]:
    lines = patch.split("\n")

    if not lines or lines[0] != "*** Begin Patch":
        raise ToolUsageError(
            "Patch must start with '*** Begin Patch'.",
            learning=LearningMetadata(
                persistent=True,
                key="apply_patch.missing_begin_marker"
            )
        )

    if lines[-1] != "*** End Patch":
        raise ToolUsageError(
            "Patch must end with '*** End Patch'.",
            learning=LearningMetadata(
                persistent=True,
                key="apply_patch.missing_end_marker"
            )
        )

    result: list[FilePatch] = []
    current: FilePatch | None = None

    for line in lines[1:-1]:
        if line.startswith("*** Update File: "):
            if current is not None:
                result.append(current)

            path = Path(
                line.removeprefix("*** Update File: ").strip()
            )

            if path.is_absolute():
                raise ToolUsageError(
                    "Patch paths must be relative to the repository.",
                    learning=LearningMetadata(
                        persistent=True,
                        key="apply_patch.non_relative_path"
                    )
                )

            path = path.as_posix()

            current = FilePatch(
                operation=Operation.UPDATE,
                path=path,
                lines=[],
            )

        elif line.startswith("*** Add File: "):
            if current is not None:
                result.append(current)

            path = Path(
                line.removeprefix("*** Add File: ").strip()
            )

            if path.is_absolute():
                raise ToolUsageError(
                    "Patch paths must be relative to the repository.",
                    learning=LearningMetadata(
                        persistent=True,
                        key="apply_patch.non_relative_path"
                    )
                )

            path = path.as_posix()

            current = FilePatch(
                operation=Operation.ADD,
                path=path,
                lines=[],
            )

        elif line.startswith("*** Delete File: "):
            if current is not None:
                result.append(current)

            path = Path(
                line.removeprefix("*** Delete File: ").strip()
            )

            if path.is_absolute():
                raise ToolUsageError(
                    "Patch paths must be relative to the repository.",
                    learning=LearningMetadata(
                        persistent=True,
                        key="apply_patch.non_relative_path"
                    )
                )

            path = path.as_posix()

            current = FilePatch(
                operation=Operation.DELETE,
                path=path,
                lines=[],
            )

        elif line.startswith("*** "):
            raise ToolUsageError(
                f"Unsupported patch metadata: {line}"
            )

        else:
            if current is None:
                if not line:
                    continue

                raise ToolUsageError(
                    "Patch content appears before a file operation.",
                    learning=LearningMetadata(
                        persistent=True,
                        key="apply_patch.content_before_operation"
                    )
                )

            current.lines.append(line)

    if current is not None:
        result.append(current)

    if not result:
        raise ToolUsageError(
            "Patch contains no file operations.",
            learning=LearningMetadata(
                persistent=True,
                key="apply_patch.empty_patch"
            )
        )

    paths = [file_patch.path for file_patch in result]

    if len(paths) != len(set(paths)):
        raise ToolUsageError(
            "Each file may appear only once in a patch; combine all changes to the same file into one file operation.",
            learning=LearningMetadata(
                persistent=True,
                key="apply_patch.duplicate_file"
            )
        )

    return result


def _apply_update(
        initial_content: str,
        lines: list[str],
) -> str:
    newline = "\r\n" if "\r\n" in initial_content else "\n"
    # Keep offsets into the original text so untouched line endings survive.
    original_lines = initial_content.split("\n")
    if original_lines[-1] == "":
        original_lines.pop()
    line_offsets = [0]
    for line in original_lines:
        line_offsets.append(min(line_offsets[-1] + len(line) + 1, len(initial_content)))
    line_texts = [line.removesuffix("\r") for line in original_lines]

    raw_hunks: list[list[str]] = []
    current: list[str] = []

    for line in lines:
        if line.startswith("@@"):
            if current:
                raw_hunks.append(current)
                current = []
            continue

        if line == "*** End of File":
            continue

        if not line.startswith((" ", "-", "+")):
            if not line:
                continue

            raise ToolUsageError(
                f"Invalid patch line: {line!r}"
            )

        current.append(line)

    if current:
        raw_hunks.append(current)

    if not raw_hunks:
        raise ToolUsageError(
            "Update File must contain at least one '@@' hunk.",
            learning=LearningMetadata(
                persistent=True,
                key="apply_patch.no_update_hunk"
            )
        )

    hunks: list[Hunk] = []

    for index, raw_hunk in enumerate(raw_hunks):
        old_lines = [
            line[1:]
            for line in raw_hunk
            if line.startswith((" ", "-"))
        ]

        new_lines = [
            line[1:]
            for line in raw_hunk
            if line.startswith((" ", "+"))
        ]

        if not old_lines:
            raise ToolUsageError(
                f"Hunk {index} contains no existing text."
            )

        matches = [
            start
            for start in range(len(line_texts) - len(old_lines) + 1)
            if line_texts[start:start + len(old_lines)] == old_lines
        ]

        if not matches:
            raise ToolUsageError(
                f"Hunk {index} target was not found."
            )

        if len(matches) > 1:
            raise ToolUsageError(
                f"Hunk {index} target is ambiguous."
            )

        start = line_offsets[matches[0]]
        end = line_offsets[matches[0] + len(old_lines)]
        new_text = newline.join(new_lines)
        if new_lines and initial_content[start:end].endswith("\n"):
            new_text += newline

        hunks.append(
            Hunk(
                start=start,
                end=end,
                new_text=new_text,
            )
        )

    hunks.sort(key=lambda hunk: hunk.start)

    for current_, next_hunk in zip(hunks, hunks[1:]):
        if next_hunk.start < current_.end:
            raise ToolUsageError(
                "Update hunks must not overlap.",
                learning=LearningMetadata(
                    persistent=True,
                    key="apply_patch.overlapping_update_hunks"
                )
            )

    content = initial_content

    for hunk in reversed(hunks):
        content = (
                content[:hunk.start]
                + hunk.new_text
                + content[hunk.end:]
        )

    return content


def _parse_added_file(lines: list[str]) -> str:
    content: list[str] = []

    for line in lines:
        if not line:
            continue

        if not line.startswith("+"):
            raise ToolUsageError(
                "Every Add File content line must start with '+'.",
                learning=LearningMetadata(
                    persistent=True,
                    key="apply_patch.invalid_add_line"
                )
            )

        content.append(line[1:])

    return "\n".join(content)
