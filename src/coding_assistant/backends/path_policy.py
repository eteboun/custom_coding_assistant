from pathlib import Path
from collections.abc import Iterable


def normalize_blocked_paths(paths: Iterable[Path]) -> set[Path]:
    normalized: set[Path] = set()

    for path in paths:
        if path.is_absolute() or path.drive or not path.parts or ".." in path.parts:
            raise ValueError(
                f"Blocked path must be relative to the repository: {path}"
            )

        normalized.add(path)

    return normalized


def is_blocked_path(
    relative: Path,
    blocked_files: set[Path],
    blocked_dirs: set[Path],
) -> bool:
    return relative in blocked_files or any(
        relative == directory or directory in relative.parents
        for directory in blocked_dirs
    )
