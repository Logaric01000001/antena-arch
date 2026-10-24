"""Estado de los archivos gestionados por Antena (solo root puede escribir)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from antena.constants import SYSTEM_STATE_DIR, SYSTEM_STATE_FILE


def empty_state() -> dict[str, Any]:
    return {"version": 1, "files": {}, "driver": None}


def load_state(path: Path | None = None) -> dict[str, Any]:
    target = path or SYSTEM_STATE_FILE
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_state()
    if not isinstance(data, dict) or data.get("version") != 1:
        return empty_state()
    data.setdefault("files", {})
    data.setdefault("driver", None)
    return data


def save_state(state: dict[str, Any], path: Path | None = None) -> None:
    target = path or SYSTEM_STATE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target.parent, 0o755)
    except OSError:
        pass
    handle, temporary = tempfile.mkstemp(prefix=".state-", dir=str(target.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(state, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def record_file(state: dict[str, Any], path: str, owner: str) -> None:
    state.setdefault("files", {})[path] = owner


def files_for(state: dict[str, Any], owner: str) -> list[str]:
    return sorted(path for path, value in state.get("files", {}).items() if value == owner)


def forget_file(state: dict[str, Any], path: str) -> None:
    state.get("files", {}).pop(path, None)


def ensure_state_dir(directory: Path | None = None) -> None:
    (directory or SYSTEM_STATE_DIR).mkdir(parents=True, exist_ok=True)
