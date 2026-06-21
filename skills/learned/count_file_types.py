import config
import safety
from pathlib import Path
from collections import defaultdict

TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "count_file_types",
        "description": "Count files by extension in a scoped folder.",
        "parameters": {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Folder to count files in."},
            },
            "required": ["folder"],
        },
    },
}

def count_file_types(folder: str) -> str:
    cfg = config.load()
    target = safety.resolve_folder(folder, cfg)   # raises if out of scope
    file_counts = defaultdict(int)
    for file in target.iterdir():
        if file.is_file():
            file_counts[file.suffix[1:]] += 1
    summary = "\n".join(f"{ext}: {count}" for ext, count in file_counts.items())
    return f"File counts for {target.name}/:\n{summary}"