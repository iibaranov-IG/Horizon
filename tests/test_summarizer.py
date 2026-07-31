"""Unit tests for daily summary rendering."""

import asyncio
from datetime import datetime, timezone
import pytest

from src.ai.summarizer import DailySummarizer
from src.models import (
    ArtifactSource,
    ClassificationResult,
    ContentAnalysis,
    ContentArtifact,
    ContentBlock,
    ContentItem,
    ProcessingResult,
    LocaleConfig,
    SourceType,
)


def _run_async(coro):
    return asyncio.run(coro)


def _make_item(idx: int) -> ContentItem:
    item = ContentItem(
        id=f"rss:item-{idx}",
        source_type=SourceType.RSS,
        title=f"Important Item {idx}",
        url=f"https://example.com/items/{idx}",
        content="content",
        author="tester",
        published_at=datetime(2026, 4, 25, 8, 0, tzinfo=timezone.utc),
        profile="tech-news",
        processing=ProcessingResult(
            classification=ClassificationResult(
                profile="tech-news", method="source_override"
            ),
            analysis=ContentAnalysis(
                score=8.0,
                reason="test",
                summary=f"Summary for item {idx}.",
                tags=["AI", "News"],
            ),
            artifacts={
                language: ContentArtifact(
                    language=language,
                    title=f"Important Item {idx}",
                    lead=f"Summary for item {idx}.",
                )
                for language in ("en", "zh")
            },
        ),
    )
    return item


def test_generate_webhook_overview_lists_items_without_full_details():
    summarizer = DailySummarizer()
    items = [_make_item(1), _make_item(2)]

    result = summarizer.generate_webhook_overview(
        items,
        date="2026-04-25",
        total_fetched=10,
        language="en",
    )

    assert "Selected 2 important items from 10 fetched items" in result
    assert "1. [Important Item 1](https://example.com/items/1)" in result
    assert "2. [Important Item 2](https://example.com/items/2)" in result
    assert "Summary for item 1." not in result


def test_generate_webhook_item_renders_single_item_detail():
    summarizer = DailySummarizer()

    result = summarizer.generate_webhook_item(
        _make_item(1),
        language="en",
        index=1,
        total=2,
    )

    assert result.startswith("Item 1/2")
    assert "## [Important Item 1](https://example.com/items/1)" in result
    assert "Summary for item 1." in result
    assert "**Tags**: `#AI`, `#News`" in result


def test_generate_webhook_item_includes_discussion_link_when_distinct():
    summarizer = DailySummarizer()
    item = _make_item(1)
    item.metadata["discussion_url"] = "https://news.ycombinator.com/item?id=1"

    result = summarizer.generate_webhook_item(
        item,
        language="en",
        index=1,
        total=1,
    )

    assert "tester · Apr 25, 08:00 · [Discussion](https://news.ycombinator.com/item?id=1)" in result


def test_generate_webhook_item_omits_discussion_link_when_same_as_item_url():
    summarizer = DailySummarizer()
    item = _make_item(1)
    item.metadata["discussion_url"] = item.url

    result = summarizer.generate_webhook_item(
        item,
        language="en",
        index=1,
        total=1,
    )

    assert "[Discussion](https://example.com/items/1)" not in result


def test_generate_webhook_item_uses_localized_discussion_label():
    summarizer = DailySummarizer()
    item = _make_item(1)
    item.metadata["discussion_url"] = "https://www.reddit.com/r/python/comments/abc123/test/"

    result = summarizer.generate_webhook_item(
        item,
        language="zh",
        index=1,
        total=1,
    )

    assert "[社区讨论](https://www.reddit.com/r/python/comments/abc123/test/)" in result


def test_generate_summary_zh_uses_localized_selection_header_and_numeric_date():
    summarizer = DailySummarizer()
    item = _make_item(1)

    result = _run_async(
        summarizer.generate_summary(
            [item],
            date="2026-04-25",
            total_fetched=10,
            language="zh",
        )
    )

    assert "> 从 10 条内容中筛选出 1 条重要资讯。" in result
    assert "rss · tester · 4月25日 08:00" in result
    assert "From 10 items" not in result
    assert "Apr 25, 08:00" not in result


def test_generate_summary_groups_items_by_profile_with_heading_hierarchy():
    news = _make_item(1)
    blog = _make_item(2)
    blog.profile = "tech-blog"
    blog.processing.classification.profile = "tech-blog"
    summarizer = DailySummarizer(
        profile_names={
            "tech-news": {"default": "Technology News", "zh": "科技新闻"},
            "tech-blog": {"default": "Technology Blog", "zh": "科技博客"},
        }
    )

    result = _run_async(
        summarizer.generate_summary(
            [news, blog],
            date="2026-04-25",
            total_fetched=2,
            language="en",
        )
    )

    assert result.count("# Horizon Daily") == 1
    assert "## Technology News" in result
    assert "## Technology Blog" in result
    assert "### [Important Item 1]" in result
    assert "### [Important Item 2]" in result


def test_generate_summary_renumbers_interleaved_profiles_and_localizes_headings():
    first_news = _make_item(1)
    blog = _make_item(2)
    second_news = _make_item(3)
    blog.profile = "tech-blog"
    blog.processing.classification.profile = "tech-blog"
    summarizer = DailySummarizer(
        profile_names={
            "tech-news": {"default": "Technology News", "zh": "科技新闻"},
            "tech-blog": {"default": "Technology Blog", "zh": "科技博客"},
        }
    )

    result = _run_async(
        summarizer.generate_summary(
            [first_news, blog, second_news],
            date="2026-04-25",
            total_fetched=3,
            language="zh",
        )
    )

    assert "## 科技新闻" in result
    assert "## 科技博客" in result
    assert "1. [Important Item 1](#item-tech-news-1)" in result
    assert "2. [Important Item 3](#item-tech-news-2)" in result
    assert "1. [Important Item 2](#item-tech-blog-1)" in result
    assert result.index("2. [Important Item 3]") < result.index("1. [Important Item 2]")
    assert '<a id="item-tech-news-1"></a>' in result
    assert '<a id="item-tech-blog-1"></a>' in result


def test_profile_heading_falls_back_to_the_primary_language_tag():
    summarizer = DailySummarizer(
        profile_names={"tech-news": {"default": "Technology News", "ru": "Новости"}}
    )

    assert summarizer.profile_name("tech-news", "ru-RU") == "Новости"


def test_generate_empty_summary_zh_uses_localized_analyzed_line():
    summarizer = DailySummarizer()

    result = _run_async(
        summarizer.generate_summary(
            [],
            date="2026-04-25",
            total_fetched=10,
            language="zh",
        )
    )

    assert "> 已分析 10 条内容，但没有达到重要性阈值的条目。" in result
    assert "Analyzed 10 items" not in result


def test_generate_summary_escapes_untrusted_text_in_all_output_contexts():
    summarizer = DailySummarizer()
    item = _make_item(1)
    item.title = '<script>alert("title")</script> [click](javascript:alert(1))'
    item.processing.analysis.summary = '<img src=x onerror="alert(1)"> **summary**'
    item.author = '<svg onload="alert(1)">'
    item.processing.analysis.tags = ['tag`](javascript:alert(1))']
    item.processing.artifacts["en"] = ContentArtifact(
        language="en",
        title=item.title,
        lead='<img src=x onerror="alert(1)"> **summary**',
        blocks=[
            ContentBlock(
                id="background",
                title="Background",
                content='<iframe src="data:text/html,bad"></iframe>',
            ),
            ContentBlock(
                id="community_discussion",
                title="Discussion",
                content="[bad](data:text/html,bad)",
            ),
        ],
        sources=[
            ArtifactSource(
                id="ref-1",
                title='<img src=x onerror="alert(1)">',
                url="https://example.com/ref",
            )
        ],
    )
    item.metadata.update(
        {
            "feed_name": '<b onclick="alert(1)">feed</b>',
        }
    )

    result = _run_async(summarizer.generate_summary([item], "2026-04-25", 1))

    assert "<script>" not in result
    assert "<img src=x" not in result
    assert "<iframe" not in result
    assert "<b onclick" not in result
    assert "](javascript:" not in result
    assert "](data:text/html" not in result
    assert "&lt;script&gt;" in result
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in result


def test_generate_summary_rejects_unsafe_urls_and_quote_injection():
    summarizer = DailySummarizer()
    item = _make_item(1)
    item.metadata["discussion_url"] = 'javascript:alert("discussion")'
    item.processing.artifacts["en"].sources = [
        ArtifactSource(
            id="quoted",
            title='Quoted "><script>alert(1)</script>',
            url='https://example.com/\" onmouseover=\"alert(1)',
        ),
        ArtifactSource(id="js", title="JavaScript", url="javascript:alert(1)"),
        ArtifactSource(
            id="data",
            title="Data",
            url="data:text/html,<script>alert(1)</script>",
        ),
    ]

    result = _run_async(summarizer.generate_summary([item], "2026-04-25", 1))

    assert 'href="https://example.com/%22%20onmouseover=%22alert%281%29"' in result
    assert '<li>JavaScript</li>' in result
    assert '<li>Data</li>' in result
    assert 'href="javascript:' not in result
    assert 'href="data:' not in result
    assert '<script>' not in result


def test_generate_summary_preserves_normal_http_links():
    summarizer = DailySummarizer()
    item = _make_item(1)
    item.metadata["discussion_url"] = "https://example.com/discuss?id=1#comments"
    item.processing.artifacts["en"].sources = [
        ArtifactSource(
            id="useful",
            title="Useful reference",
            url="https://docs.example.com/path?q=one&lang=en",
        )
    ]

    result = _run_async(summarizer.generate_summary([item], "2026-04-25", 1))

    assert "[Important Item 1](https://example.com/items/1)" in result
    assert "[Discussion](https://example.com/discuss?id=1#comments)" in result
    assert 'href="https://docs.example.com/path?q=one&amp;lang=en"' in result


def test_russian_summary_uses_russian_labels_and_item_prefix():
    summarizer = DailySummarizer()
    item = _make_item(1)
    item.processing.artifacts["ru"] = ContentArtifact(
        language="ru",
        title="Важная новость",
        lead="Краткое русскоязычное описание.",
        blocks=[],
    )

    summary = _run_async(summarizer.generate_summary([item], "2026-07-31", 1, language="ru"))
    webhook_item = summarizer.generate_webhook_item(item, "ru", 1, 3)

    assert "# Horizon: ежедневная сводка - 2026-07-31" in summary
    assert "Отобрано: 1 важная новость из 1 материала." in summary
    assert "Важная новость" in summary
    assert webhook_item.startswith("Новость 1 из 3")


def test_russian_overview_and_item_metadata_are_fully_localized():
    summarizer = DailySummarizer()
    items = [_make_item(1), _make_item(2)]
    for item in items:
        item.processing.artifacts["ru"] = ContentArtifact(
            language="ru", title="Важная новость", lead="Краткое описание."
        )
    items[0].author = None
    items[0].published_at = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)

    overview = summarizer.generate_webhook_overview(items, "2026-07-31", 5, language="ru")
    item_message = summarizer.generate_webhook_item(items[0], "ru", 1, 2)

    assert "Отобрано: 2 важные новости из 5 материалов." in overview
    assert "Подробности будут отправлены отдельными сообщениями" in overview
    assert "Selected" not in overview
    assert "неизвестный автор · 31 июля, 08:00" in item_message
    assert "Jul" not in item_message


def test_custom_locale_configures_rendering_without_a_code_change():
    summarizer = DailySummarizer(
        locales={
            "fr": {
                "header": "Horizon : synthèse",
                "selected_items": "{selected} sélection sur {total} éléments.",
                "overview_instruction": "Les détails suivent.",
                "item_prefix": "Actualité {index}/{total}",
                "date_format": "%d/%m, %H:%M",
                "unknown_author": "auteur inconnu",
            }
        }
    )
    item = _make_item(1)
    item.processing.artifacts["fr"] = ContentArtifact(
        language="fr", title="Nouvelle importante", lead="Résumé français."
    )
    item.author = None

    overview = summarizer.generate_webhook_overview([item], "2026-04-25", 3, language="fr")
    item_message = summarizer.generate_webhook_item(item, "fr", 1, 1)

    assert "# Horizon : synthèse - 2026-04-25" in overview
    assert "1 sélection sur 3 éléments." in overview
    assert "Les détails suivent." in overview
    assert item_message.startswith("Actualité 1/1")
    assert "auteur inconnu · 25/04, 08:00" in item_message


def test_partial_builtin_locale_override_preserves_its_native_rules():
    summarizer = DailySummarizer(
        locales={"ru": LocaleConfig(header="Горизонт: обзор")}
    )
    item = _make_item(1)
    item.processing.artifacts["ru"] = ContentArtifact(
        language="ru", title="Новость", lead="Описание."
    )
    item.published_at = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)

    summary = _run_async(summarizer.generate_summary([item], "2026-07-31", 1, "ru"))
    item_message = summarizer.generate_webhook_item(item, "ru", 1, 1)

    assert "# Горизонт: обзор - 2026-07-31" in summary
    assert "Отобрано: 1 важная новость из 1 материала." in summary
    assert "31 июля, 08:00" in item_message


def test_locale_config_rejects_invalid_runtime_formatting_rules():
    with pytest.raises(ValueError, match="month_names"):
        LocaleConfig(month_names=["январь"] * 11)
    with pytest.raises(ValueError, match="item_prefix may only use"):
        LocaleConfig(item_prefix="Новость {number}")
    with pytest.raises(ValueError, match="placeholders require month_names"):
        LocaleConfig(date_format="{day} {month}")


def test_underscore_language_tag_uses_its_builtin_locale_in_production():
    summarizer = DailySummarizer(strict_locales=True)

    summarizer.validate_locale_configuration("zh_CN")
    assert summarizer._locale("zh_CN")["header"] == "Horizon 每日速递"


def test_uppercase_builtin_language_tag_uses_its_builtin_locale_in_production():
    summarizer = DailySummarizer(strict_locales=True)

    summarizer.validate_locale_configuration("ZH_cn")
    assert summarizer._locale("ZH_cn")["header"] == "Horizon 每日速递"


def test_production_custom_locale_requires_a_language_safe_date_format():
    locale = LocaleConfig(
        header="FR",
        discussion="Discussion",
        references="Sources",
        tags="Tags",
        unknown_author="inconnu",
        selected_items="{selected}/{total}",
        empty_analyzed="{total}",
        empty_body="Vide",
        overview_instruction="Suite",
        collapsible_overview_instruction="Suite",
        item_prefix="{index}/{total}",
        webhook_daily_title="{date}",
        webhook_overview_title="{date}",
        webhook_collapsible_title="{date}",
    )
    summarizer = DailySummarizer(locales={"fr": locale}, strict_locales=True)

    with pytest.raises(ValueError, match="date_format"):
        summarizer.validate_locale_configuration("fr")


def test_production_rejects_an_artifact_with_a_mismatched_declared_language():
    item = _make_item(1)
    item.processing.artifacts["en"] = ContentArtifact(
        language="fr", title="English title", lead="English lead"
    )
    summarizer = DailySummarizer(strict_locales=True)

    with pytest.raises(ValueError, match="declares language='fr'"):
        summarizer._validate_language_output([item], "en")
