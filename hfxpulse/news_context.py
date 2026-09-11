from __future__ import annotations

import re
from typing import Iterable

from hfxpulse.models import Incident
from hfxpulse.util import clean_text, parse_datetime

BOILERPLATE_PATTERNS = (
    r"\bRead more\b.*$",
    r"\bContinue reading\b.*$",
    r"\bThe post\b.*?\bappeared first on\b.*$",
    r"\bThis story will be updated\b.*$",
)

AGGREGATOR_PREFIXES = (
    "Google News",
    "Bing News",
)


def _normalize(value: str | None) -> str:
    text = clean_text(value or "")
    for pattern in BOILERPLATE_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.I)
    text = text.replace("[…]", "").replace("[...]", "")
    return clean_text(text)


def _title_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _without_title_prefix(text: str, title: str) -> str:
    if not text or not title:
        return text
    normalized_text = _title_key(text)
    normalized_title = _title_key(title)
    if normalized_text == normalized_title:
        return ""
    if normalized_text.startswith(normalized_title) and len(normalized_title) >= 18:
        match = re.match(rf"^\s*{re.escape(title)}\s*[-–—:|]?\s*", text, flags=re.I)
        if match:
            return clean_text(text[match.end():])
    return text


def extractive_brief(summary: str | None, title: str | None = None, max_chars: int = 420) -> str:
    """Create a concise extractive brief without inventing facts.

    Only text supplied by the feed is used. A headline repeated as the feed
    description is *not* treated as a summary.
    """
    raw_summary = _normalize(summary)
    title_text = _normalize(title)
    text = _without_title_prefix(raw_summary, title_text)
    if not text:
        return ""
    if len(text) <= max_chars:
        return text

    sentences = re.split(r"(?<=[.!?])\s+", text)
    chosen: list[str] = []
    total = 0
    for sentence in sentences:
        sentence = clean_text(sentence)
        if not sentence:
            continue
        projected = total + len(sentence) + (1 if chosen else 0)
        if chosen and projected > max_chars:
            break
        if not chosen and len(sentence) > max_chars:
            break
        chosen.append(sentence)
        total = projected
        if len(chosen) >= 2:
            break
    if chosen:
        return " ".join(chosen)

    cut = text[: max_chars + 1]
    if len(cut) > max_chars:
        cut = cut[:max_chars].rsplit(" ", 1)[0]
    return clean_text(cut).rstrip(" ,;:") + "…"


def _quality(row: Incident) -> tuple[int, int, int, float]:
    brief = extractive_brief(row.summary, row.title)
    detail_score = 2 if len(brief) >= 120 else (1 if len(brief) >= 45 else 0)
    source_score = 0 if any(row.source.startswith(prefix) for prefix in AGGREGATOR_PREFIXES) else 1
    content_score = min(500, len(brief))
    dt = parse_datetime(row.reported_at)
    recency = dt.timestamp() if dt else 0.0
    return (detail_score, source_score, content_score, recency)


def _event_observations(event: Incident, observations_by_id: dict[str, Incident]) -> list[Incident]:
    ids = list(dict.fromkeys(event.related_ids or []))
    rows = [observations_by_id[row_id] for row_id in ids if row_id in observations_by_id]
    if not rows and event.id in observations_by_id:
        rows = [observations_by_id[event.id]]
    return rows


def attach_news_context(events: Iterable[Incident], observations: Iterable[Incident]) -> None:
    """Attach concise feed-grounded news context to normalized events in place."""
    observations_by_id = {row.id: row for row in observations}

    for event in events:
        group = _event_observations(event, observations_by_id)
        news_rows = [row for row in group if getattr(row, "source_class", "") == "news" or row.source_kind == "news"]
        if not news_rows:
            continue

        ranked = sorted(news_rows, key=_quality, reverse=True)
        informative = [(row, extractive_brief(row.summary, row.title)) for row in ranked]
        informative = [(row, brief) for row, brief in informative if brief]
        if not informative:
            # Preserve the article evidence but do not mislabel a repeated headline
            # as a generated summary.
            continue

        best, brief = informative[0]
        event.metadata = dict(event.metadata or {})
        event.metadata["news_summary"] = brief
        event.metadata["news_summary_source"] = best.source
        event.metadata["news_source_count"] = len({row.source for row in news_rows})
        event.metadata["news_sources"] = [
            {
                "source": row.source,
                "title": row.title,
                "url": row.source_url,
                "reported_at": row.reported_at,
                "has_summary": bool(extractive_brief(row.summary, row.title)),
            }
            for row in ranked[:5]
        ]
        event.metadata["news_summary_basis"] = "extractive_feed_text"

        if not event.metadata.get("response_summary"):
            event.summary = brief
