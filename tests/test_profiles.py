import json
import shutil
from pathlib import Path

import pytest

import src.processing.profiles as profile_module
from src.processing import ProfileRegistry


def test_loads_builtin_tech_news_profile():
    registry = ProfileRegistry.load(
        Path(__file__).resolve().parents[1] / "profiles", "tech-news"
    )

    profile = registry.get("tech-news")
    assert profile.definition.filter.enabled is True
    assert profile.definition.filter.threshold == 8.0
    assert [block.id for block in profile.definition.enrichment.blocks] == [
        "summary",
        "background",
        "community_discussion",
    ]
    assert profile.definition.enrichment.blocks[1].tools == ["web_search"]
    assert "3-6 complete sentences" in profile.enrichment_prompt
    assert "2-4 complete sentences" in profile.enrichment_prompt
    assert "1-3 complete sentences" in profile.enrichment_prompt
    assert "no more than 15 words" in profile.enrichment_prompt
    assert "untrusted reference material" not in profile.enrichment_prompt
    assert "untrusted data, not instructions" not in profile.analysis_prompt
    assert "three to five specific topic tags" in profile.analysis_prompt
    assert "Technology news profile" in profile.match_prompt


def test_loads_builtin_tech_blog_profile():
    registry = ProfileRegistry.load(
        Path(__file__).resolve().parents[1] / "profiles", "tech-news"
    )

    profile = registry.get("tech-blog")
    assert profile.definition.filter.enabled is False
    assert profile.definition.filter.threshold is None
    assert profile.definition.display_names["zh"] == "科技博客"
    assert profile.definition.content.analysis_max_chars == 16000
    assert profile.definition.content.enrichment_max_chars == 24000
    assert profile.definition.content.sampling == "head-middle-tail"
    assert profile.definition.topic_dedup.enabled is False
    assert [block.id for block in profile.definition.enrichment.blocks] == ["story"]
    assert profile.definition.enrichment.blocks[0].tools == []
    assert "300-500 Chinese characters" in profile.enrichment_prompt
    assert "Technology blog profile" in profile.match_prompt


def test_production_validation_checks_every_loaded_profile_for_auto_routing():
    registry = ProfileRegistry.load(
        Path(__file__).resolve().parents[1] / "profiles", "tech-news"
    )
    registry.get("tech-blog").definition.display_names.pop("ru")

    with pytest.raises(ValueError, match="tech-blog"):
        registry.validate_output_languages(["ru"], strict=True)


def test_example_config_includes_enabled_nvidia_tech_blog_source():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "data" / "config.example.json").read_text())
    source = next(
        source
        for source in config["sources"]["rss"]
        if source["name"] == "NVIDIA CUDA Technical Blog"
    )

    assert source == {
        "name": "NVIDIA CUDA Technical Blog",
        "url": "https://developer.nvidia.com/blog/tag/cuda/feed/",
        "enabled": True,
        "category": "cuda",
        "profile": "tech-blog",
        "content_extractor": "trafilatura",
    }


def test_default_profiles_fall_back_to_packaged_resources(tmp_path, monkeypatch):
    packaged_profiles = tmp_path / "packaged-profiles"
    source_profiles = Path(__file__).resolve().parents[1] / "profiles"
    shutil.copytree(source_profiles, packaged_profiles)
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    monkeypatch.chdir(working_dir)
    monkeypatch.setattr(profile_module, "BUILTIN_PROFILES_DIR", packaged_profiles)

    registry = ProfileRegistry.load(Path("profiles"), "tech-news")

    assert registry.get("tech-news").analysis_prompt


def test_relative_profiles_dir_resolves_from_config_directory(tmp_path, monkeypatch):
    source_profiles = Path(__file__).resolve().parents[1] / "profiles"
    config_dir = tmp_path / "etc" / "horizon"
    shutil.copytree(source_profiles, config_dir / "profiles")
    unrelated_working_dir = tmp_path / "elsewhere"
    unrelated_working_dir.mkdir()
    monkeypatch.chdir(unrelated_working_dir)

    registry = ProfileRegistry.load(
        Path("profiles"), "tech-news", base_dir=config_dir
    )

    assert registry.get("tech-news").analysis_prompt


def test_default_example_profiles_path_resolves_from_data_config_directory():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "data" / "config.example.json").read_text())

    registry = ProfileRegistry.load(
        Path(config["processing"]["profiles_dir"]),
        config["processing"]["default_profile"],
        base_dir=root / "data",
    )

    assert registry.get("tech-news").analysis_prompt


def test_rejects_enabled_filter_without_threshold(tmp_path):
    profile_dir = tmp_path / "invalid"
    profile_dir.mkdir()
    for name in ("match.md", "analysis.md", "enrichment.md"):
        (profile_dir / name).write_text("prompt", encoding="utf-8")
    (profile_dir / "profile.json").write_text(
        json.dumps(
            {
                "id": "invalid",
                "name": "Invalid",
                "match": "match.md",
                "analysis": "analysis.md",
                "filter": {"enabled": True},
                "enrichment": {
                    "prompt": "enrichment.md",
                    "blocks": [{"id": "body", "type": "section", "tools": []}],
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="threshold"):
        ProfileRegistry.load(tmp_path, "invalid")


def test_rejects_prompt_path_outside_profile_directory(tmp_path):
    profile_dir = tmp_path / "invalid"
    profile_dir.mkdir()
    (tmp_path / "outside.md").write_text("prompt", encoding="utf-8")
    (profile_dir / "analysis.md").write_text("prompt", encoding="utf-8")
    (profile_dir / "enrichment.md").write_text("prompt", encoding="utf-8")
    (profile_dir / "profile.json").write_text(
        json.dumps(
            {
                "id": "invalid",
                "name": "Invalid",
                "match": "../outside.md",
                "analysis": "analysis.md",
                "filter": {"enabled": False},
                "enrichment": {
                    "prompt": "enrichment.md",
                    "blocks": [{"id": "body", "type": "section", "tools": []}],
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="escapes"):
        ProfileRegistry.load(tmp_path, "invalid")
