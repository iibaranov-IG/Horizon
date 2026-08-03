"""Storage manager for configuration and state persistence."""

import json
import os
import re
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .._file_utils import _atomic_write_text
from ..models import Config, base_language


# Matches ${VAR_NAME} in string config values. Names follow env-var rules
# (ASCII letters, digits, underscore; must not start with a digit).
_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_LANGUAGE_TAG_PATTERN = re.compile(r"^[A-Za-z]{2,8}(?:[-_][A-Za-z0-9]{1,8})*$")


def safe_output_path(root: Path, filename: str) -> Path:
    """Return an output path only when it resolves below root."""
    resolved_root = root.resolve()
    candidate = (resolved_root / filename).resolve()
    if candidate.parent != resolved_root:
        raise ValueError(f"Output path escapes intended root: {candidate}")
    return candidate


def _expand_env_vars(value: Any) -> Any:
    """Recursively expand ``${VAR}`` references inside any string leaves.

    Containers (dicts, lists, tuples) are walked; non-string leaves are
    returned unchanged. Strings with no ``${...}`` tokens are returned
    unchanged. References to unset variables are **left as-is**, so
    ``${MISSING}`` round-trips to ``${MISSING}`` and surfaces as a clear
    downstream error rather than a silent empty string.

    This is intentionally identical to the behaviour ``RSSScraper`` uses
    for RSS feed URLs, so a single ``${VAR}`` convention works everywhere
    in the config (AI ``base_url``, feed URLs, webhook URLs, ...).
    """
    if isinstance(value, str):
        return _ENV_VAR_PATTERN.sub(
            lambda m: os.environ.get(m.group(1), m.group(0)),
            value,
        )
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_expand_env_vars(v) for v in value)
    return value


def _load_locale_files(data: dict[str, Any], config_path: Path) -> dict[str, Any]:
    """Merge per-language JSON files into ``ai.locales``.

    Locale files are named after a language tag (for example ``ru.json``),
    live in ``ai.locales_dir``, and are overridden by inline ``ai.locales``.
    """
    ai = data.get("ai")
    if not isinstance(ai, dict) or not ai.get("locales_dir"):
        return data

    raw_dir = Path(str(ai["locales_dir"])).expanduser()
    locales_dir = raw_dir if raw_dir.is_absolute() else config_path.parent / raw_dir
    if not locales_dir.is_dir():
        raise ConfigError(f"Locale directory does not exist: {locales_dir}")

    locales: dict[str, dict[str, Any]] = {}
    configured_languages = {
        base_language(str(language))
        for language in ai.get("languages", [])
        if isinstance(language, str)
    }
    for locale_path in sorted(locales_dir.glob("*.json")):
        language = locale_path.stem
        if not _LANGUAGE_TAG_PATTERN.fullmatch(language):
            raise ConfigError(f"Invalid locale filename: {locale_path.name}")
        if configured_languages and base_language(language) not in configured_languages:
            continue
        try:
            payload = json.loads(locale_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Invalid locale JSON: {locale_path}") from exc
        if not isinstance(payload, dict):
            raise ConfigError(f"Locale file must contain a JSON object: {locale_path}")
        locales[language] = payload

    inline = ai.get("locales", {})
    if not isinstance(inline, dict):
        raise ConfigError("ai.locales must be a JSON object")
    for language, overrides in inline.items():
        if not isinstance(overrides, dict):
            raise ConfigError(f"ai.locales.{language} must be a JSON object")
        locales[language] = {**locales.get(language, {}), **overrides}

    data = dict(data)
    data["ai"] = {**ai, "locales": locales}
    return data


class ConfigError(ValueError):
    """Raised when configuration is missing or invalid."""

    pass


class StorageManager:
    """Manages file-based storage for configuration and state."""

    def __init__(self, data_dir: str = "data", config_path: str | None = None):
        self.data_dir = Path(data_dir)
        self.config_path = Path(config_path) if config_path is not None else self.data_dir / "config.json"
        self.summaries_dir = self.data_dir / "summaries"
        # Keep the authored inline overrides separate from the effective merged
        # locale configuration.  Locale files remain the source of truth when
        # a loaded configuration is written back out.
        self._inline_locales: dict[str, Any] | None = None

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.summaries_dir.mkdir(parents=True, exist_ok=True)

    def load_config(self) -> Config:
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {self.config_path}\n"
                f"Please create it based on the template in README.md"
            )

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigError(
                f"Invalid JSON in configuration file: {self.config_path}\n" f"Error: {e}"
            ) from e

        ai = data.get("ai")
        if isinstance(ai, dict) and isinstance(ai.get("locales"), dict):
            self._inline_locales = deepcopy(ai["locales"])
        else:
            self._inline_locales = {}
        data = _load_locale_files(data, self.config_path)

        # Expand ${VAR} references in every string value before pydantic
        # validation. Keeps credentials / private endpoints / tenant IDs
        # out of the JSON file so it is safe to commit to a public repo.
        data = _expand_env_vars(data)

        try:
            return Config.model_validate(data)
        except ValidationError as e:
            raise ConfigError(
                f"Configuration validation failed for {self.config_path}\n"
                f"Details: {e}"
            ) from e

    def save_config(
        self,
        config: Config,
        backup: bool = True,
        *,
        save_effective_locales: bool = False,
    ) -> Path:
        """Save configuration to config.json, optionally backing up the existing file.

        Args:
            config: The Config object to save.
            backup: If True and config.json exists, copy it to config.json.bak first.
            save_effective_locales: If True, write the effective merged locale
                packages into ``ai.locales``. Use this explicit opt-in only for
                tools that intentionally edit inline locale overrides.

        Returns:
            Path to the saved config file.
        """
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        if backup and self.config_path.exists():
            shutil.copy2(self.config_path, self.config_path.with_suffix(".json.bak"))

        payload = config.model_dump(mode="json")
        # ``load_config`` merges file packages into ``config.ai.locales`` for
        # runtime use.  Do not serialize that merged view: doing so would make
        # stale values in config.json shadow future edits to locale files.
        if (
            not save_effective_locales
            and self._inline_locales is not None
            and isinstance(payload.get("ai"), dict)
        ):
            payload["ai"]["locales"] = self._inline_locales
        content = json.dumps(payload, indent=2, ensure_ascii=False)
        _atomic_write_text(self.config_path, f"{content}\n")

        return self.config_path

    def save_daily_summary(self, date: str, markdown: str, language: str = "en") -> Path:
        filename = f"horizon-{date}-{language}.md"
        filepath = safe_output_path(self.summaries_dir, filename)

        _atomic_write_text(filepath, markdown)

        return filepath

    def load_subscribers(self) -> list:
        """Loads the list of email subscribers."""
        subscribers_path = self.data_dir / "subscribers.json"
        if not subscribers_path.exists():
            return []

        try:
            with open(subscribers_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []

    def add_subscriber(self, email_addr: str):
        """Adds a new subscriber email."""
        subscribers = self.load_subscribers()
        if email_addr not in subscribers:
            subscribers.append(email_addr)
            self._save_subscribers(subscribers)

    def remove_subscriber(self, email_addr: str):
        """Removes a subscriber email."""
        subscribers = self.load_subscribers()
        if email_addr in subscribers:
            subscribers.remove(email_addr)
            self._save_subscribers(subscribers)

    def _save_subscribers(self, subscribers: list):
        """Helper to save subscribers list."""
        subscribers_path = self.data_dir / "subscribers.json"
        _atomic_write_text(subscribers_path, json.dumps(subscribers, indent=2))
