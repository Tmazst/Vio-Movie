from pathlib import Path
from datetime import datetime
from typing import Any

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"
}

DOCUMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".txt", ".rtf", ".md"
}

SPREADSHEET_EXTENSIONS = {
    ".xls", ".xlsx", ".csv", ".ods"
}

AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"
}

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"
}

CODE_EXTENSIONS = {
    ".py", ".js", ".html", ".css", ".json", ".sql"
}

SKIP_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".idea",
    ".vscode",
}


def categorize_file(path: Path) -> str:
    """Determine a file's category from its extension and folder names."""

    extension = path.suffix.lower()
    folder_names = {
        part.lower().replace("_", " ").replace("-", " ")
        for part in path.parts[:-1]
    }
    folder_text = " ".join(folder_names)

    if extension in IMAGE_EXTENSIONS:
        if "character" in folder_text:
            return "character_reference"
        if "location" in folder_text:
            return "location_reference"
        if "prop" in folder_text:
            return "prop_reference"
        return "image"

    if extension in VIDEO_EXTENSIONS:
        return "video"

    if extension in AUDIO_EXTENSIONS:
        return "audio"

    if extension in SPREADSHEET_EXTENSIONS:
        if "log" in folder_text or "generation" in folder_text:
            return "generation_log"
        return "spreadsheet"

    if extension in DOCUMENT_EXTENSIONS:
        if "script" in folder_text:
            return "script"
        if any(
            keyword in folder_text
            for keyword in ("bible", "instruction", "continuity", "reference")
        ):
            return "production_document"
        return "document"

    if extension in CODE_EXTENSIONS:
        return "code"

    return "other"


def scan_project(root_path: str) -> dict[str, Any]:
    """
    Scan an existing production directory without modifying its contents.

    Returns a structured inventory of files and summary counts.
    """

    root = Path(root_path).expanduser()

    if not root.exists():
        raise FileNotFoundError(
            f"Project folder does not exist: {root}"
        )

    if not root.is_dir():
        raise NotADirectoryError(
            f"Project path is not a directory: {root}"
        )

    files = []
    errors = []

    def on_walk_error(error: OSError) -> None:
        errors.append({
            "path": str(error.filename or root),
            "message": str(error),
        })

    for current_path, directories, filenames in __import__("os").walk(
        root,
        onerror=on_walk_error,
    ):
        directories[:] = sorted(
            directory
            for directory in directories
            if directory.lower() not in SKIP_DIRECTORIES
        )

        current = Path(current_path)

        for filename in sorted(filenames):
            path = current / filename

            try:
                if path.is_symlink():
                    continue

                stat = path.stat()

                files.append({
                    "name": path.name,
                    "relative_path": path.relative_to(root).as_posix(),
                    "absolute_path": str(path.resolve()),
                    "extension": path.suffix.lower(),
                    "category": categorize_file(path),
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(
                        stat.st_mtime
                    ).isoformat(timespec="seconds"),
                })

            except (OSError, ValueError) as error:
                errors.append({
                    "path": str(path),
                    "message": str(error),
                })

    files.sort(key=lambda item: item["relative_path"].lower())

    categories = {}

    for file in files:
        category = file["category"]
        categories[category] = categories.get(category, 0) + 1

    return {
        "project_root": str(root.resolve()),
        "scanned_at": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "total_files": len(files),
        "total_size_bytes": sum(
            file["size_bytes"] for file in files
        ),
        "categories": categories,
        "files": files,
        "errors": errors,
    }