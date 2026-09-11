from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, iso_utc, parse_datetime, stable_id

URL = "https://www.halifax.ca/home/news?category=25"
SOURCE = "Halifax Regional Police"

DATE_RE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"\d{1,2},\s+\d{4}(?:\s*(?:-\s*)?\d{1,2}:\d{2}\s*(?:AM|PM))?",
    re.I,
)


def _parse_posted(value: str) -> str | None:
    text = clean_text(value)
    text = re.sub(r"^Posted:\s*", "", text, flags=re.I)
    match = DATE_RE.search(text)
    if not match:
        return None
    normalized = re.sub(r"\s+-\s+", " ", match.group(0))
    return iso_utc(parse_datetime(normalized))


def _severity(text: str) -> int:
    lower = text.lower()
    return 2 if any(w in lower for w in ("closure", "weapon", "firearm", "collision", "evac", "shoot", "stabb")) else 1


def _build_row(title: str, href: str, reported: str, summary: str) -> Incident:
    full = urljoin(URL, href)
    return Incident(
        id=f"hrp-{stable_id(full)}",
        source=SOURCE,
        source_url=full,
        title=title,
        summary=summary[:500],
        category="POLICE",
        subtype="media_release",
        reported_at=reported,
        severity=_severity(f"{title} {summary}"),
        signals=["official_release"],
    )


def _nearest_dated_context(link) -> tuple[str, re.Match | None]:
    node = link.parent
    last = clean_text(link.get_text(" ", strip=True))
    for _ in range(8):
        if node is None:
            break
        last = clean_text(node.get_text(" ", strip=True))
        match = DATE_RE.search(last)
        if match:
            return last, match
        node = node.parent
    return last, None


def parse_hrp_html(html: str) -> list[Incident]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Incident] = []
    seen: set[str] = set()

    # Current production markup: bind date/title/summary inside one list item so
    # a neighbouring release can never lend this card its timestamp.
    cards = soup.select("li.c-news-updates__list-item")
    for card in cards:
        link = card.select_one("a.c-news-updates__list-item-link[href]") or card.select_one("a[href]")
        date_node = card.select_one(".c-news-updates__date")
        if not link or not date_node:
            continue

        title = clean_text(link.get_text(" ", strip=True))
        href = clean_text(link.get("href", ""))
        if len(title) < 5 or "/home/news/" not in href:
            continue

        full = urljoin(URL, href)
        if full in seen:
            continue

        reported = _parse_posted(date_node.get_text(" ", strip=True))
        if not reported:
            continue

        summary_node = card.select_one(".c-news-update__content")
        summary = clean_text(summary_node.get_text(" ", strip=True) if summary_node else "")
        context = clean_text(card.get_text(" ", strip=True))
        seen.add(full)
        rows.append(_build_row(title, href, reported, summary or context))

    if rows:
        return rows

    # Fallback for minor markup shifts. This retains the broad Build 003 parser
    # without weakening the card-bound parser used for the known current page.
    for link in soup.select("a[href]"):
        title = clean_text(link.get_text(" ", strip=True))
        href = clean_text(link.get("href", ""))
        if len(title) < 12 or "/home/news/" not in href:
            continue
        full = urljoin(URL, href)
        if full in seen:
            continue
        context, date_match = _nearest_dated_context(link)
        if not date_match:
            continue
        reported = _parse_posted(date_match.group(0))
        if not reported:
            continue
        seen.add(full)
        rows.append(_build_row(title, href, reported, context))

    return rows


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, timeout=25)
        res.raise_for_status()
        rows = parse_hrp_html(res.text)
        if not rows:
            raise ValueError("HRP news page fetched but no dated police release cards or fallback links were parsed")
        return rows

    return guarded_fetch(
        SOURCE,
        URL,
        "official",
        run,
        notes="Official HRP releases; current release-card parser with a bounded dated-link fallback.",
    )
