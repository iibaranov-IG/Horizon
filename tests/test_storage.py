import json
import asyncio
import shutil
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast

import pytest
from pathlib import Path
import src._file_utils as file_utils
from src.storage.manager import StorageManager, ConfigError, _expand_env_vars, safe_output_path
from src.ai.summarizer import DailySummarizer
from src.models import (
    AIConfig, Config, ClassificationResult, ContentAnalysis, ContentArtifact,
    ContentItem, ProcessingResult, SourceType, WebhookConfig,
)
from src.processing import ProfileRegistry
from src.services.webhook import WebhookNotifier
from pydantic import ValidationError

def test_load_config_missing_file(tmp_path):
    storage = StorageManager(data_dir=str(tmp_path))
    with pytest.raises(FileNotFoundError):
        storage.load_config()

def test_load_config_invalid_json(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("invalid json", encoding="utf-8")
    
    storage = StorageManager(data_dir=str(tmp_path))
    with pytest.raises(ConfigError) as excinfo:
        storage.load_config()
    assert "Invalid JSON in configuration file" in str(excinfo.value)
    assert str(config_path) in str(excinfo.value)

def test_load_config_validation_failure(tmp_path):
    config_path = tmp_path / "config.json"
    # Missing required 'ai' and 'sources' fields
    config_path.write_text(json.dumps({}), encoding="utf-8")
    
    storage = StorageManager(data_dir=str(tmp_path))
    with pytest.raises(ConfigError) as excinfo:
        storage.load_config()
    assert "Configuration validation failed" in str(excinfo.value)
    assert str(config_path) in str(excinfo.value)

def test_load_config_success(tmp_path):
    config_path = tmp_path / "config.json"
    config_data = {
        "ai": {
            "provider": "anthropic",
            "model": "claude-3-sonnet",
            "api_key_env": "ANTHROPIC_API_KEY"
        },
        "sources": {
            "hackernews": {"enabled": True}
        },
        "collection": {
            "time_window_hours": 24
        }
    }
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    
    storage = StorageManager(data_dir=str(tmp_path))
    config = storage.load_config()
    assert config.collection.time_window_hours == 24
    assert config.ai.provider == "anthropic"


def test_load_config_merges_locale_files_with_inline_overrides(tmp_path):
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    (locales_dir / "fr.json").write_text(
        json.dumps({"header": "Horizon France", "item_prefix": "Actualité {index}/{total}"}),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "ai": {
                    "provider": "openai",
                    "model": "test",
                    "api_key_env": "OPENAI_API_KEY",
                    "languages": ["fr"],
                    "locales_dir": "locales",
                    "locales": {"fr": {"header": "Horizon France override"}},
                },
                "sources": {},
            }
        ),
        encoding="utf-8",
    )

    config = StorageManager(data_dir=str(tmp_path)).load_config()

    assert config.ai.locales["fr"].header == "Horizon France override"
    assert config.ai.locales["fr"].item_prefix == "Actualité {index}/{total}"


@pytest.mark.parametrize(
    ("filename", "payload", "error"),
    [
        ("invalid!.json", "{}", "Invalid locale filename"),
        ("fr.json", "not json", "Invalid locale JSON"),
        ("fr.json", "[]", "Locale file must contain a JSON object"),
    ],
)
def test_load_config_rejects_invalid_locale_files(tmp_path, filename, payload, error):
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    (locales_dir / filename).write_text(payload, encoding="utf-8")
    (tmp_path / "config.json").write_text(json.dumps({
        "ai": {"provider": "openai", "model": "test", "api_key_env": "KEY",
               "languages": ["fr"], "locales_dir": "locales"}, "sources": {},
    }), encoding="utf-8")

    with pytest.raises(ConfigError, match=error):
        StorageManager(data_dir=str(tmp_path)).load_config()


def test_load_config_rejects_missing_locale_directory(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({
        "ai": {"provider": "openai", "model": "test", "api_key_env": "KEY",
               "locales_dir": "missing"}, "sources": {},
    }), encoding="utf-8")

    with pytest.raises(ConfigError, match="Locale directory does not exist"):
        StorageManager(data_dir=str(tmp_path)).load_config()


def test_save_config_keeps_locale_files_as_source_of_truth(tmp_path):
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    locale_path = locales_dir / "fr.json"
    locale_path.write_text(
        json.dumps({"header": "Horizon France v1", "item_prefix": "Actualité {index}/{total}"}),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "ai": {
                    "provider": "openai",
                    "model": "test",
                    "api_key_env": "OPENAI_API_KEY",
                    "languages": ["fr"],
                    "locales_dir": "locales",
                    "locales": {"fr": {"tags": "Étiquettes locales"}},
                },
                "sources": {},
            }
        ),
        encoding="utf-8",
    )

    storage = StorageManager(data_dir=str(tmp_path))
    config = storage.load_config()
    storage.save_config(config, backup=False)

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["ai"]["locales"] == {"fr": {"tags": "Étiquettes locales"}}

    locale_path.write_text(
        json.dumps({"header": "Horizon France v2", "item_prefix": "Actualité {index}/{total}"}),
        encoding="utf-8",
    )
    reloaded = storage.load_config()
    assert reloaded.ai.locales["fr"].header == "Horizon France v2"
    assert reloaded.ai.locales["fr"].tags == "Étiquettes locales"


def test_save_config_can_explicitly_write_effective_locale_overrides(tmp_path):
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    (locales_dir / "fr.json").write_text(
        json.dumps({"header": "Horizon France", "item_prefix": "Actualité {index}/{total}"}),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "ai": {
                    "provider": "openai", "model": "test", "api_key_env": "OPENAI_API_KEY",
                    "languages": ["fr"], "locales_dir": "locales", "locales": {},
                },
                "sources": {},
            }
        ),
        encoding="utf-8",
    )
    storage = StorageManager(data_dir=str(tmp_path))
    config = storage.load_config()
    config.ai.locales["fr"].header = "Horizon France edited"

    storage.save_config(config, backup=False, save_effective_locales=True)

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["ai"]["locales"]["fr"]["header"] == "Horizon France edited"

    (locales_dir / "fr.json").write_text(
        json.dumps({"header": "Horizon France changed", "item_prefix": "Actualité {index}/{total}"}),
        encoding="utf-8",
    )
    assert storage.load_config().ai.locales["fr"].header == "Horizon France edited"


def test_custom_production_locale_flows_from_file_to_summary_and_webhook(tmp_path):
    source_profile = Path(__file__).resolve().parents[1] / "profiles" / "tech-news"
    profiles_dir = tmp_path / "profiles"
    shutil.copytree(source_profile, profiles_dir / "tech-news")
    profile_path = profiles_dir / "tech-news" / "profile.json"
    profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
    profile_data["display_names"]["fr"] = "Actualités techniques"
    profile_path.write_text(json.dumps(profile_data), encoding="utf-8")

    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    locale = {
        "header": "Horizon : synthèse", "discussion": "Discussion",
        "references": "Sources", "tags": "Étiquettes", "unknown_author": "inconnu",
        "selected_items": "{selected} sur {total}", "empty_analyzed": "{total}",
        "empty_body": "Aucune actualité.", "overview_instruction": "La suite.",
        "collapsible_overview_instruction": "Ouvrez les cartes.",
        "item_prefix": "Actualité {index}/{total}", "date_format": "%d/%m, %H:%M",
        "webhook_daily_title": "Horizon {date}", "webhook_overview_title": "Aperçu {date}",
        "webhook_collapsible_title": "Cartes {date}",
    }
    (locales_dir / "fr.json").write_text(json.dumps(locale), encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "ai": {"provider": "openai", "model": "test", "api_key_env": "OPENAI_API_KEY",
               "languages": ["fr"], "locales_dir": "locales", "locale_mode": "production"},
        "processing": {"profiles_dir": str(profiles_dir), "default_profile": "tech-news"},
        "sources": {},
    }), encoding="utf-8")

    config = StorageManager(data_dir=str(tmp_path)).load_config()
    profiles = ProfileRegistry.load(Path(config.processing.profiles_dir), "tech-news")
    profiles.validate_output_languages(config.ai.languages, strict=True)
    summarizer = DailySummarizer(profiles.names, config.ai.locales, strict_locales=True)
    item = ContentItem(
        id="rss:1", source_type=SourceType.RSS, title="Original", url="https://example.com",
        published_at=datetime(2026, 4, 25, 8, 0, tzinfo=timezone.utc),
        processing=ProcessingResult(
            classification=ClassificationResult(profile="tech-news", method="source_override"),
            analysis=ContentAnalysis(score=9, reason="test", summary="Original"),
            artifacts={"fr": ContentArtifact(language="fr", title="Nouvelle", lead="Résumé")},
        ),
    )
    summary = asyncio.run(summarizer.generate_summary([item], "2026-04-25", 1, "fr"))
    messages = WebhookNotifier(WebhookConfig(platform="feishu", layout="collapsible")).build_daily_summary_messages(
        summary, [item], 1, "2026-04-25", "fr", summarizer
    )

    assert "Horizon : synthèse" in summary
    assert "25/04, 08:00" in summary
    assert messages[0]["message_title"] == "Cartes 2026-04-25"


@pytest.mark.parametrize(
    ("legacy_key", "legacy_value"),
    [
        ("version", "2.0"),
        ("filtering", {"time_window_hours": 24}),
    ],
)
def test_config_rejects_removed_top_level_fields(legacy_key, legacy_value):
    data = {
        "ai": {
            "provider": "openai",
            "model": "test",
            "api_key_env": "OPENAI_API_KEY",
        },
        "sources": {},
        legacy_key: legacy_value,
    }

    with pytest.raises(ValidationError):
        Config.model_validate(data)


def test_custom_config_path_overrides_data_directory(tmp_path):
    config_path = tmp_path / "config" / "custom.json"
    storage = StorageManager(
        data_dir=str(tmp_path / "data"),
        config_path=str(config_path),
    )

    assert storage.config_path == config_path


def test_save_config_creates_custom_config_parent(tmp_path):
    config_path = tmp_path / "config" / "nested" / "custom.json"
    storage = StorageManager(
        data_dir=str(tmp_path / "data"),
        config_path=str(config_path),
    )
    config = cast(Config, SimpleNamespace(model_dump=lambda mode: {"example": "value"}))

    assert storage.save_config(config) == config_path
    assert json.loads(config_path.read_text(encoding="utf-8")) == {"example": "value"}


class TestExpandEnvVars:
    """Recursive ${VAR} expansion on config dicts/lists/strings."""

    def test_expands_simple_reference(self, monkeypatch):
        monkeypatch.setenv("FOO", "bar")
        assert _expand_env_vars("prefix-${FOO}-suffix") == "prefix-bar-suffix"

    def test_expands_multiple_references_in_one_string(self, monkeypatch):
        monkeypatch.setenv("A", "1")
        monkeypatch.setenv("B", "2")
        assert _expand_env_vars("${A}/${B}") == "1/2"

    def test_leaves_unset_var_as_placeholder(self, monkeypatch):
        monkeypatch.delenv("MISSING", raising=False)
        assert _expand_env_vars("${MISSING}") == "${MISSING}"

    def test_ignores_non_matching_patterns(self):
        assert _expand_env_vars("no braces here") == "no braces here"
        assert _expand_env_vars("$FOO without braces") == "$FOO without braces"
        assert _expand_env_vars("${123INVALID}") == "${123INVALID}"

    def test_recurses_into_dict(self, monkeypatch):
        monkeypatch.setenv("HOST", "api.example.com")
        result = _expand_env_vars({"url": "https://${HOST}/v1", "port": 443})
        assert result == {"url": "https://api.example.com/v1", "port": 443}

    def test_recurses_into_list(self, monkeypatch):
        monkeypatch.setenv("X", "hi")
        assert _expand_env_vars(["${X}", "plain", 7]) == ["hi", "plain", 7]

    def test_preserves_non_string_leaves(self):
        assert _expand_env_vars(42) == 42
        assert _expand_env_vars(3.14) == 3.14
        assert _expand_env_vars(True) is True
        assert _expand_env_vars(None) is None

    def test_deeply_nested(self, monkeypatch):
        monkeypatch.setenv("TOKEN", "secret")
        value = {
            "a": [
                {"b": "Bearer ${TOKEN}"},
                {"b": ["${TOKEN}", 1]},
            ],
        }
        out = _expand_env_vars(value)
        assert out["a"][0]["b"] == "Bearer secret"
        assert out["a"][1]["b"] == ["secret", 1]


def test_load_config_expands_env_vars_in_ai_base_url(tmp_path, monkeypatch):
    """Integration: proves base_url is env-expandable end-to-end.

    This is exactly the use case that keeps private/tenant endpoint
    URLs out of version control.
    """
    monkeypatch.setenv("HORIZON_AI_BASE_URL", "https://private-proxy.example/v1")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "ai": {
            "provider": "openai",
            "model": "gpt-4o",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "${HORIZON_AI_BASE_URL}",
        },
        "sources": {"hackernews": {"enabled": True}},
        "collection": {"time_window_hours": 24},
    }), encoding="utf-8")

    storage = StorageManager(data_dir=str(tmp_path))
    config = storage.load_config()
    assert config.ai.base_url == "https://private-proxy.example/v1"


@pytest.mark.parametrize("language", ["en", "zh-CN", "pt_BR", "sr-Latn-RS"])
def test_ai_config_accepts_normal_language_codes(language):
    config = AIConfig(provider="openai", model="gpt-4o", api_key_env="OPENAI_API_KEY", languages=[language])
    assert config.languages == [language]


@pytest.mark.parametrize("language", ["../outside", "en/../../outside", "en\\outside", ".", ""])
def test_ai_config_rejects_unsafe_language_codes(language):
    with pytest.raises(ValidationError):
        AIConfig(provider="openai", model="gpt-4o", api_key_env="OPENAI_API_KEY", languages=[language])


def test_save_daily_summary_defensively_rejects_path_escape(tmp_path):
    storage = StorageManager(data_dir=str(tmp_path / "data"))
    with pytest.raises(ValueError, match="escapes intended root"):
        storage.save_daily_summary("2026-07-13", "secret", language="../../../../outside")
    assert not (tmp_path / "outside.md").exists()


def test_safe_output_path_rejects_escape_from_other_output_roots(tmp_path):
    with pytest.raises(ValueError, match="escapes intended root"):
        safe_output_path(tmp_path / "docs" / "_posts", "../../../outside.md")


def test_save_daily_summary_replace_failure_preserves_destination(tmp_path, monkeypatch):
    storage = StorageManager(data_dir=str(tmp_path))
    destination = storage.save_daily_summary("2026-07-13", "existing")

    def fail_replace(source, target):
        raise OSError("replace failed")

    monkeypatch.setattr(file_utils.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        storage.save_daily_summary("2026-07-13", "replacement")

    assert destination.read_text(encoding="utf-8") == "existing"
    assert list(destination.parent.glob(f".{destination.name}.*.tmp")) == []


def test_save_subscribers_replace_failure_preserves_destination(tmp_path, monkeypatch):
    storage = StorageManager(data_dir=str(tmp_path))

    def fail_replace(source, target):
        raise OSError("replace failed")

    monkeypatch.setattr(file_utils.os, "replace", fail_replace)

    subscribers_path = tmp_path / "subscribers.json"
    subscribers_path.write_text('["old"]', encoding="utf-8")
    with pytest.raises(OSError, match="replace failed"):
        storage._save_subscribers(["new"])

    assert subscribers_path.read_text(encoding="utf-8") == '["old"]'
    assert list(tmp_path.glob(f".{subscribers_path.name}.*.tmp")) == []
