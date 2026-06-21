import config
import safety
from pathlib import Path

TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "count_files_in_folder",
        "description": "Count the number of files in a given folder.",
        "parameters": {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Folder to count files in."},
            },
            "required": ["folder"],
        },
    },
}

def count_files_in_folder(folder: str) -> str:
    cfg = config.load()
    target = safety.resolve_folder(folder, cfg)  # raises if out of scope
    file_count = sum(1 for _ in target.iterdir() if _.is_file())
    return f"Found {file_count} files in folder '{target.name}'"