"""Daily summary generation — pure programmatic rendering."""

import html
import re
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import quote, urlsplit

from ..models import ContentItem, base_language


_CJK = r"[\u4e00-\u9fff\u3400-\u4dbf]"
_ASCII = r"[A-Za-z0-9]"
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()<>#!|])")
_MARKDOWN_BLOCK_START = re.compile(r"(?m)^( {0,3})(>|[-+] |\d+[.)] )")
_URL_SAFE_CHARS = ":/?#[]@!$&'*,;=~%+"
_RUSSIAN_MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def _escape_markdown(value: object) -> str:
    """Render untrusted text literally while retaining its readable content."""
    escaped = html.escape(str(value), quote=True)
    escaped = _MARKDOWN_SPECIAL.sub(r"\\\1", escaped)
    return _MARKDOWN_BLOCK_START.sub(r"\1\\\2", escaped)


def _safe_url(value: object) -> Optional[str]:
    """Return an HTML/Markdown-safe HTTP(S) URL, or None for unsafe URLs."""
    raw = str(value).strip()
    if not raw or any(ord(char) < 32 or ord(char) == 127 for char in raw):
        return None
    try:
        parsed = urlsplit(raw)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return None
        parsed.port
    except (TypeError, ValueError):
        return None
    encoded = quote(raw, safe=_URL_SAFE_CHARS)
    return html.escape(encoded, quote=True)


def _pangu(text: str) -> str:
    """Insert a space between CJK and ASCII letters/digits (Pangu spacing)."""
    text = re.sub(rf"({_CJK})({_ASCII})", r"\1 \2", text)
    text = re.sub(rf"({_ASCII})({_CJK})", r"\1 \2", text)
    return text


LABELS = {
    "en": {
        "header": "Horizon Daily",
        "discussion": "Discussion",
        "references": "References",
        "tags": "Tags",
        "selected_items": "From {total} items, {selected} important content pieces were selected",
        "overview_selected_items": "Selected {selected} important items from {total} fetched items.",
        "empty_analyzed": "Analyzed {total} items, but none met the importance threshold.",
        "empty_body": (
            "No significant developments today. This might indicate:\n"
            "- A quiet day in your tracked sources\n"
            "- The AI score threshold is too high\n"
            "- Your information sources need expansion\n\n"
            "Consider:\n"
            "1. Lowering the active profile's filter threshold\n"
            "2. Adding more diverse information sources\n"
            "3. Checking if the AI model is working correctly\n"
        ),
        "item_prefix": "Item {index}/{total}",
        "date_format": "%b %-d, %H:%M",
        "overview_instruction": "Details will be sent item by item so you can read only the topics you care about.",
        "collapsible_overview_instruction": "Expand the panels below to read the full briefing inside Feishu/Lark.",
    },
    "zh": {
        "header": "Horizon 每日速递",
        "discussion": "社区讨论",
        "references": "参考链接",
        "tags": "标签",
        "selected_items": "从 {total} 条内容中筛选出 {selected} 条重要资讯。",
        "overview_selected_items": "从 {total} 条内容中筛选出 {selected} 条重要资讯。",
        "empty_analyzed": "已分析 {total} 条内容，但没有达到重要性阈值的条目。",
        "empty_body": (
            "今日暂无重要动态，可能原因：\n"
            "- 今天关注的信息源较平静\n"
            "- AI 评分阈值设置过高\n"
            "- 信息源种类有待扩充\n\n"
            "建议：\n"
            "1. 降低当前 Profile 的过滤阈值\n"
            "2. 添加更多多样化的信息源\n"
            "3. 检查 AI 模型是否正常工作\n"
        ),
        "item_prefix": "第 {index}/{total} 条",
        "pangu_spacing": True,
        "overview_instruction": "下面会按内容逐条发送详情，你可以只看感兴趣的标题。",
        "collapsible_overview_instruction": "点击下方新闻面板即可在飞书内展开阅读全文。",
    },
    "ru": {
        "header": "Horizon: ежедневная сводка",
        "discussion": "Обсуждение",
        "references": "Ссылки",
        "tags": "Теги",
        "unknown": "неизвестный автор",
        "empty_body": (
            "Сегодня значимых обновлений не найдено. Возможные причины:\n"
            "- отслеживаемые источники были спокойны\n"
            "- порог оценки AI установлен слишком высоко\n"
            "- список источников стоит расширить\n\n"
            "Рекомендуем:\n"
            "1. Снизить порог фильтра активного профиля\n"
            "2. Добавить надёжные тематические источники\n"
            "3. Проверить, что AI-модель отвечает корректно\n"
        ),
        "item_prefix": "Новость {index} из {total}",
        "plural_rule": "russian",
        "date_format": "{day} {month}, {time}",
        "month_names": list(_RUSSIAN_MONTHS_GENITIVE),
        "collapsible_overview_instruction": "Раскройте карточки ниже, чтобы прочитать полный материал в Feishu/Lark.",
        "overview_instruction": "Подробности будут отправлены отдельными сообщениями — можно читать только интересующие темы.",
    },
}


@dataclass(frozen=True)
class SummaryItemView:
    item: ContentItem
    index: int
    global_index: int
    group_count: int
    title: str
    score: float | str
    anchor_id: str


@dataclass(frozen=True)
class SummaryGroupView:
    profile_id: str
    name: str
    items: List[SummaryItemView]


@dataclass(frozen=True)
class DailySummaryView:
    groups: List[SummaryGroupView]
    item_count: int


class DailySummarizer:
    """Generates daily Markdown summaries from pre-analyzed content items."""

    def __init__(
        self,
        profile_names: Optional[Dict[str, Dict[str, str]]] = None,
        locales: Optional[Dict[str, object]] = None,
        strict_locales: bool = False,
    ):
        self.profile_names = profile_names or {}
        self.locales = locales or {}
        self.strict_locales = strict_locales

    def _validate_language_output(self, items: List[ContentItem], language: str) -> None:
        """Reject mixed-language production output before rendering it."""
        if not self.strict_locales:
            return
        self.validate_locale_configuration(language)
        for item in items:
            if not item.processing or language not in item.processing.artifacts:
                raise ValueError(
                    f"Item {item.id} has no localized artifact for language={language!r}"
                )
            artifact = item.processing.artifacts[language]
            if artifact.language != language:
                raise ValueError(
                    f"Item {item.id} artifact key {language!r} declares "
                    f"language={artifact.language!r}"
                )

    def validate_locale_configuration(self, language: str) -> None:
        """Validate locale completeness without waiting for fetched content."""
        if not self.strict_locales:
            return
        builtin = {"en", "zh", "ru"}
        primary_language = base_language(language)
        if primary_language not in builtin and not (
            self.locales.get(language) or self.locales.get(primary_language)
        ):
            raise ValueError(f"No locale package configured for language={language!r}")
        if primary_language not in builtin:
            locale = self.locales.get(language) or self.locales.get(primary_language)
            fields = (
                locale.model_fields_set
                if hasattr(locale, "model_fields_set")
                else set(locale)
            )
            required = {
                "header", "discussion", "references", "tags", "unknown_author",
                "selected_items", "empty_analyzed", "empty_body",
                "overview_instruction", "collapsible_overview_instruction",
                "item_prefix", "date_format", "webhook_daily_title", "webhook_overview_title",
                "webhook_collapsible_title",
            }
            missing = sorted(required - fields)
            if missing:
                raise ValueError(
                    f"Locale {language!r} is incomplete in production: {', '.join(missing)}"
                )
            date_format = locale.date_format if hasattr(locale, "date_format") else locale["date_format"]
            locale_sensitive_directives = re.compile(r"%(?:a|A|b|B|c|p|r|x|X|Z)")
            if locale_sensitive_directives.search(date_format):
                raise ValueError(
                    f"Locale {language!r} date_format must not use locale-sensitive "
                    "strftime directives in production"
                )

    def _locale(self, language: str) -> dict:
        """Resolve a config locale, falling back to a built-in base language."""
        primary_language = base_language(language)
        configured = self.locales.get(language) or self.locales.get(primary_language)
        if configured:
            values = (
                configured.model_dump(exclude_none=True, exclude_unset=True)
                if hasattr(configured, "model_dump")
                else dict(configured)
            )
            labels = dict(
                LABELS.get(language, LABELS.get(primary_language, LABELS["en"]))
            )
            labels.update({
                "unknown": values.pop("unknown_author", labels.get("unknown", "unknown")),
                **values,
            })
            return labels
        return LABELS.get(language, LABELS.get(primary_language, LABELS["en"]))

    @staticmethod
    def _russian_plural(count: int, forms: tuple[str, str, str]) -> str:
        """Choose the Russian singular/few/many form for a non-negative count."""
        remainder = count % 100
        if 11 <= remainder <= 14:
            return forms[2]
        remainder = count % 10
        if remainder == 1:
            return forms[0]
        if 2 <= remainder <= 4:
            return forms[1]
        return forms[2]

    def selection_text(self, total: int, selected: int, language: str) -> str:
        """Return the localized sentence describing filtering results."""
        labels = self._locale(language)
        if labels.get("plural_rule") == "russian":
            materials = self._russian_plural(total, ("материала", "материалов", "материалов"))
            news = self._russian_plural(selected, ("важная новость", "важные новости", "важных новостей"))
            return f"Отобрано: {selected} {news} из {total} {materials}."
        return labels["selected_items"].format(total=total, selected=selected)

    def overview_selection_text(self, total: int, selected: int, language: str) -> str:
        """Return the localized selection line for a compact webhook overview."""
        labels = self._locale(language)
        if labels.get("plural_rule") == "russian":
            return self.selection_text(total, selected, language)
        primary_language = base_language(language)
        configured = self.locales.get(language) or self.locales.get(primary_language)
        configured_values = (
            configured.model_dump(exclude_none=True, exclude_unset=True)
            if hasattr(configured, "model_dump")
            else dict(configured or {})
        )
        # A custom locale that supplies its normal selection label should not
        # inherit the English compact-overview wording by accident.
        template = configured_values.get(
            "overview_selected_items",
            labels["selected_items"]
            if configured_values
            else labels.get("overview_selected_items", labels["selected_items"]),
        )
        return template.format(total=total, selected=selected)

    def empty_selection_text(self, total: int, language: str) -> str:
        """Return the localized empty-digest status line."""
        labels = self._locale(language)
        if labels.get("plural_rule") == "russian":
            materials = self._russian_plural(total, ("материал", "материала", "материалов"))
            verb = "Проанализирован" if total % 100 != 11 and total % 10 == 1 else "Проанализировано"
            return f"{verb} {total} {materials}, но ни один не прошёл порог важности."
        return labels["empty_analyzed"].format(total=total)

    def overview_instruction(self, language: str) -> str:
        return self._locale(language)["overview_instruction"]

    def _format_published_at(self, published_at, language: str) -> str:
        labels = self._locale(language)
        month_names = labels.get("month_names")
        date_format = labels.get("date_format", "%b %-d, %H:%M")
        if month_names:
            return date_format.format(
                day=published_at.day,
                month=month_names[published_at.month - 1],
                time=published_at.strftime("%H:%M"),
            )
        if labels.get("pangu_spacing", False):
            return f"{published_at.month}月{published_at.day}日 {published_at:%H:%M}"
        return published_at.strftime(date_format)

    @staticmethod
    def _profile_id(item: ContentItem) -> str:
        if item.processing:
            return item.processing.classification.profile
        return item.profile or "unclassified"

    def profile_name(self, profile_id: str, language: str) -> str:
        names = self.profile_names.get(profile_id, {})
        return names.get(
            language,
            names.get(
                base_language(language),
                names.get(
                "default",
                profile_id.replace("-", " ").replace("_", " ").title(),
                ),
            ),
        )

    def build_view(
        self,
        items: List[ContentItem],
        language: str,
    ) -> DailySummaryView:
        grouped_items: Dict[str, List[ContentItem]] = {}
        for item in items:
            grouped_items.setdefault(self._profile_id(item), []).append(item)

        groups = []
        global_index = 1
        for profile_id, profile_items in grouped_items.items():
            view_items = []
            for index, item in enumerate(profile_items, start=1):
                artifact = (
                    item.processing.artifacts.get(language)
                    if item.processing
                    else None
                )
                analysis = item.processing.analysis if item.processing else None
                view_items.append(
                    SummaryItemView(
                        item=item,
                        index=index,
                        global_index=global_index,
                        group_count=len(profile_items),
                        title=artifact.title if artifact else item.title,
                        score=(
                            analysis.score
                            if analysis and analysis.score is not None
                            else "?"
                        ),
                        anchor_id=self._item_anchor(profile_id, index),
                    )
                )
                global_index += 1
            groups.append(
                SummaryGroupView(
                    profile_id=profile_id,
                    name=self.profile_name(profile_id, language),
                    items=view_items,
                )
            )
        return DailySummaryView(groups=groups, item_count=len(items))

    @staticmethod
    def _item_anchor(profile_id: str, index: int) -> str:
        safe_profile_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", profile_id).strip("-")
        return f"item-{safe_profile_id or 'unclassified'}-{index}"

    async def generate_summary(
        self,
        items: List[ContentItem],
        date: str,
        total_fetched: int,
        language: str = "en",
    ) -> str:
        """Generate daily summary in Markdown format.

        Items are rendered in score-descending order (already sorted by orchestrator).

        Args:
            items: High-scoring content items (already enriched)
            date: Date string (YYYY-MM-DD)
            total_fetched: Total number of items fetched before filtering
            language: Output language configured in ``ai.languages``.

        Returns:
            str: Markdown formatted summary
        """
        labels = self._locale(language)

        self._validate_language_output(items, language)

        if not items:
            return self._generate_empty_summary(date, total_fetched, labels, language)

        header = (
            f"# {labels['header']} - {date}\n\n"
            f"> {self.selection_text(total_fetched, len(items), language)}\n\n"
            "---\n\n"
        )

        toc_sections = []
        body_sections = []
        view = self.build_view(items, language)
        for group in view.groups:
            profile_name = _escape_markdown(group.name)
            if self._locale(language).get("pangu_spacing", False):
                profile_name = _pangu(profile_name)
            toc_entries = [f"**{profile_name}**"]
            for view_item in group.items:
                title = _escape_markdown(view_item.title)
                if self._locale(language).get("pangu_spacing", False):
                    title = _pangu(title)
                toc_entries.append(
                    f"{view_item.index}. [{title}](#{view_item.anchor_id}) "
                    f"\u2b50\ufe0f {view_item.score}/10"
                )
            toc_sections.append("\n".join(toc_entries))
            body_sections.append(f"## {profile_name}\n\n")
            body_sections.extend(
                self._format_item(
                    view_item.item,
                    labels,
                    language,
                    view_item.index,
                    heading_level=3,
                    anchor_id=view_item.anchor_id,
                    title_override=view_item.title,
                    score_override=view_item.score,
                )
                for view_item in group.items
            )

        toc = "\n\n".join(toc_sections) + "\n\n---\n\n"
        return header + toc + "".join(body_sections)

    def generate_webhook_overview(
        self,
        items: List[ContentItem],
        date: str,
        total_fetched: int,
        language: str = "en",
    ) -> str:
        """Generate a compact overview for multi-message webhook delivery."""
        labels = self._locale(language)
        if not items:
            return self._generate_empty_summary(date, total_fetched, labels, language)

        header = (
            f"# {labels['header']} - {date}\n\n"
            f"> {self.overview_selection_text(total_fetched, len(items), language)}\n\n"
            f"{self.overview_instruction(language)}\n\n"
        )

        sections = []
        view = self.build_view(items, language)
        for group in view.groups:
            profile_name = _escape_markdown(group.name)
            if self._locale(language).get("pangu_spacing", False):
                profile_name = _pangu(profile_name)
            entries = [f"**{profile_name}**"]
            for view_item in group.items:
                title = _escape_markdown(view_item.title)
                if self._locale(language).get("pangu_spacing", False):
                    title = _pangu(title)
                url = _safe_url(view_item.item.url)
                title_link = f"[{title}]({url})" if url else title
                entries.append(
                    f"{view_item.index}. {title_link} "
                    f"\u2b50\ufe0f {view_item.score}/10"
                )
            sections.append("\n".join(entries))

        return header + "\n\n".join(sections)

    def generate_webhook_item(
        self,
        item: ContentItem,
        language: str,
        index: int,
        total: int,
        *,
        title: Optional[str] = None,
        score: float | str | None = None,
    ) -> str:
        """Generate one item message for multi-message webhook delivery."""
        labels = self._locale(language)
        prefix = self._locale(language).get("item_prefix", "Item {index}/{total}").format(
            index=index, total=total
        ) + "\n\n"
        return prefix + self._format_item(
            item,
            labels,
            language,
            index,
            title_override=title,
            score_override=score,
        ).rstrip("-\n ")

    def _format_item(
        self,
        item: ContentItem,
        labels: dict,
        language: str,
        index: int,
        *,
        heading_level: int = 2,
        anchor_id: Optional[str] = None,
        title_override: Optional[str] = None,
        score_override: float | str | None = None,
    ) -> str:
        """Format a single ContentItem into Markdown."""
        artifact = item.processing.artifacts.get(language) if item.processing else None
        analysis = item.processing.analysis if item.processing else None
        _title = title_override or (artifact.title if artifact else item.title)
        title = _escape_markdown(_title)
        raw_url = str(item.url)
        url = _safe_url(raw_url)
        score = (
            score_override
            if score_override is not None
            else analysis.score
            if analysis and analysis.score is not None
            else "?"
        )
        meta = item.metadata

        summary = artifact.lead if artifact else analysis.summary if analysis else ""

        summary = _escape_markdown(summary)

        if self._locale(language).get("pangu_spacing", False):
            title = _pangu(title)
            summary = _pangu(summary)

        # Source line with parts joined by " · ", link appended at end
        source_type = item.source_type.value
        source_parts = [_escape_markdown(source_type)]
        if meta.get("subreddit"):
            source_parts.append(_escape_markdown(f"r/{meta['subreddit']}"))
        if meta.get("feed_name"):
            source_parts.append(_escape_markdown(meta["feed_name"]))
        else:
            source_parts.append(_escape_markdown(item.author or labels.get("unknown", "unknown")))
        if item.published_at:
            source_parts.append(self._format_published_at(item.published_at, language))
        source_line = " \u00b7 ".join(source_parts)  # ·

        discussion_url = meta.get("discussion_url")
        if discussion_url:
            safe_discussion_url = _safe_url(discussion_url)
            if safe_discussion_url and str(discussion_url) != raw_url:
                source_line += f' · [{labels["discussion"]}]({safe_discussion_url})'

        title_link = f"[{title}]({url})" if url else title

        lines = [
            f'<a id="{anchor_id or f"item-{index}"}"></a>',
            f"{'#' * heading_level} {title_link} \u2b50\ufe0f {score}/10",  # ⭐️
            "",
            summary,
            "",
            source_line,
        ]

        if artifact:
            for block in artifact.blocks:
                block_title = _escape_markdown(block.title)
                block_content = _escape_markdown(block.content)
                if self._locale(language).get("pangu_spacing", False):
                    block_title = _pangu(block_title)
                    block_content = _pangu(block_content)
                lines.extend(
                    ["", f"{'#' * (heading_level + 1)} {block_title}", "", block_content]
                )

        sources = artifact.sources if artifact else []
        if sources:
            reference_items = []
            for source in sources:
                reference_title = html.escape(source.title, quote=True)
                reference_url = _safe_url(source.url)
                if reference_url:
                    reference_items.append(f'<li><a href="{reference_url}">{reference_title}</a></li>\n')
                else:
                    reference_items.append(f"<li>{reference_title}</li>\n")
            items_html = "".join(reference_items)
            lines += [
                "",
                f'<details><summary>{labels["references"]}</summary>\n<ul>\n{items_html}\n</ul>\n</details>',
            ]

        if analysis and analysis.tags:
            tags_str = ", ".join([f"`#{_escape_markdown(t)}`" for t in analysis.tags])
            lines.append("")
            lines.append(f"**{labels['tags']}**: {tags_str}")

        lines.append("")
        lines.append("---")

        return "\n".join(lines) + "\n\n"

    def _generate_empty_summary(
        self, date: str, total_fetched: int, labels: dict, language: str
    ) -> str:
        """Generate summary when no high-scoring items were found."""
        return (
            f"# {labels['header']} - {date}\n\n"
            f"> {self.empty_selection_text(total_fetched, language)}\n\n"
            + labels["empty_body"]
        )
