import config
import safety
from pathlib import Path

TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "find_largest_files",
        "description": "Find the five largest files in a given folder.",
        "parameters": {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Folder to search."}
            },
            "required": ["folder"],
        },
    },
}

def find_largest_files(folder: str) -> str:
    cfg = config.load()
    target = safety.resolve_folder(folder, cfg)   # raises if out of scope
    files = [f for f in target.iterdir() if f.is_file()]
    largest_files = sorted(files, key=lambda f: f.stat().st_size, reverse=True)[:5]
    report = "\n".join(f"{f.name}: {f.stat().st_size / (1024*1024):.2f} MB" for f in largest_files)
    return f"Found largest files in {target.name}/:\n{report}"