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
        # Remove the literal title when feeds repeat it before the useful excerpt.
        match = re.match(rf"^\s*{re.escape(title)}\s*[-–—:|]?\s*", text, flags=re.I)
        if match:
            return clean_text(text[match.end():])
    return text


def extractive_brief(summary: str | None, title: str | None = None, max_chars: int = 420) -> str:
    """Create a concise extractive brief without inventing facts.

    This only trims/cleans text already supplied by a feed. It never adds facts,
    causal claims, names, locations or timing that are absent from the source text.
    """
    text = _normalize(summary)
    text = _without_title_prefix(text, _normalize(title))
    if not text:
        text = _normalize(title)
    if len(text) <= max_chars:
        return text

    # Prefer complete sentences, capped at roughly two sentences.
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


def _quality(row: Incident) -> tuple[int, int, float]:
    summary = extractive_brief(row.summary, row.title)
    source_penalty = -2 if any(row.source.startswith(prefix) for prefix in AGGREGATOR_PREFIXES) else 0
    content_score = min(500, len(summary))
    dt = parse_datetime(row.reported_at)
    recency = dt.timestamp() if dt else 0.0
    return (source_penalty, content_score, recency)


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
        best = ranked[0]
        brief = extractive_brief(best.summary, best.title)
        if not brief:
            continue

        event.metadata = dict(event.metadata or {})
        event.metadata["news_summary"] = brief
        event.metadata["news_source_count"] = len({row.source for row in news_rows})
        event.metadata["news_sources"] = [
            {
                "source": row.source,
                "title": row.title,
                "url": row.source_url,
                "reported_at": row.reported_at,
            }
            for row in ranked[:5]
        ]
        event.metadata["news_summary_basis"] = "extractive_feed_text"

        # Preserve a specialized emergency-response summary when present. For all
        # other events, the best feed excerpt becomes the human-readable summary.
        if not event.metadata.get("response_summary"):
            event.summary = brief
