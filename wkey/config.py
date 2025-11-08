"""Persistent configuration management for wkey."""
from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Tuple


SETTINGS_PATH = Path.home() / ".wkey.json"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "hotkey": "ctrl_r",
    "mouse_button": "",
    "enable_keyboard_shortcut": True,
    "enable_mouse_shortcut": True,
    "whisper_backend": "",
    "groq_api_key": "",
    "openai_api_key": "",
    "llm_correct": False,
    "llm_prompt": "",
    "chinese_conversion": "",
}


def load_settings() -> Tuple[Dict[str, Any], bool]:
    """Load settings from disk, returning defaults and whether user overrides exist."""
    data: Dict[str, Any] = {}
    has_overrides = False
    if SETTINGS_PATH.exists():
        try:
            with SETTINGS_PATH.open("r", encoding="utf-8") as fh:
                data = json.load(fh) or {}
            print(f"Loading settings from {SETTINGS_PATH}")
            has_overrides = bool(data)
        except Exception as exc:
            print(f"Failed to load settings from {SETTINGS_PATH}: {exc}")
            data = {}
    merged = deepcopy(DEFAULT_SETTINGS)
    merged.update(data or {})
    return merged, has_overrides


def save_settings(settings: Dict[str, Any]) -> None:
    """Persist settings to disk."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SETTINGS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
    print(f"Saved settings to {SETTINGS_PATH}")


def apply_settings(settings: Dict[str, Any], clear_missing: bool = False) -> None:
    """Sync selected settings into environment variables for wkey."""
    if not settings:
        return

    allow_empty = {"WKEY", "WKEY_MOUSE_BUTTON"}

    mapping = {
        "WKEY": settings.get("hotkey"),
        "WKEY_MOUSE_BUTTON": settings.get("mouse_button"),
        "WKEY_KEYBOARD_ENABLED": "true" if settings.get("enable_keyboard_shortcut", True) else "false",
        "WKEY_MOUSE_ENABLED": "true" if settings.get("enable_mouse_shortcut", True) else "false",
        "WHISPER_BACKEND": settings.get("whisper_backend"),
        "GROQ_API_KEY": settings.get("groq_api_key"),
        "OPENAI_API_KEY": settings.get("openai_api_key"),
        "LLM_CORRECT": "true" if settings.get("llm_correct") else "",
        "LLM_CORRECT_PROMPT": settings.get("llm_prompt"),
        "CHINESE_CONVERSION": settings.get("chinese_conversion"),
    }

    def _resolved_value(env_key: str, candidate: Any) -> Any:
        """Prefer explicit setting; fall back to existing environment value."""
        if candidate == "" and env_key in allow_empty:
            return ""
        if candidate == "" and env_key in allow_empty:
            return ""
        if candidate not in ("", None):
            return candidate
        return os.environ.get(env_key)

    for env_key, value in mapping.items():
        resolved = _resolved_value(env_key, value)
        if resolved == "":
            os.environ.pop(env_key, None)
        elif resolved not in (None,):
            os.environ[env_key] = resolved
        elif clear_missing:
            os.environ.pop(env_key, None)
