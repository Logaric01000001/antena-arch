"""Preferencias locales del usuario (sin GSettings ni servicios)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from antena.i18n import detect_system_language, set_language


@dataclass
class Settings:
    language: str = "auto"
    appearance: str = "system"  # system | light | dark
    advanced: bool = False

    @property
    def effective_language(self) -> str:
        return detect_system_language() if self.language == "auto" else self.language


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "antena" / "config.json"


def load_settings(path: Path | None = None) -> Settings:
    target = path or config_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    language = data.get("language", "auto")
    appearance = data.get("appearance", "system")
    if language not in {"auto", "es", "en"}:
        language = "auto"
    if appearance not in {"system", "light", "dark"}:
        appearance = "system"
    settings = Settings(language=language, appearance=appearance, advanced=bool(data.get("advanced", False)))
    set_language(settings.effective_language)
    return settings


def save_settings(settings: Settings, path: Path | None = None) -> None:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(settings), indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def current_settings() -> Settings:
    return load_settings()
