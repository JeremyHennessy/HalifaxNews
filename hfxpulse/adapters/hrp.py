from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, iso_utc, parse_datetime, stable_id

URL = "https://www.halifax.ca/home/news?category=25"
SOURCE = "Halifax Regional Police"

POLICE_TERMS = (
    "police", "collision", "road closure", "weapons", "firearm", "emergency", "missing", "arrest",
    "traffic", "investigation", "bomb", "suspicious", "evacuation", "downtown", "waterfront"
)

DATE_RE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"\d{1,2},\s+\d{4}(?:\s+-\s+\d{1,2}:\d{2}\s*(?:AM|PM))?",
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


def parse_hrp_html(html: str) -> list[Incident]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Incident] = []
    seen: set[str] = set()

    # Current Halifax news markup groups each release in a list item. Keeping the
    # date/title/summary inside that explicit boundary prevents dates from an
    # adjacent release being attached to the wrong link when inner divs change.
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

        seen.add(full)
        summary_node = card.select_one(".c-news-update__content")
        summary = clean_text(summary_node.get_text(" ", strip=True) if summary_node else "")
        context = clean_text(card.get_text(" ", strip=True))
        text = f"{title} {summary or context}".lower()
        severity = 2 if any(w in text for w in ("closure", "weapon", "firearm", "collision", "evac")) else 1

        rows.append(
            Incident(
                id=f"hrp-{stable_id(full)}",
                source=SOURCE,
                source_url=full,
                title=title,
                summary=(summary or context)[:500],
                category="POLICE",
                subtype="media_release",
                reported_at=reported,
                severity=severity,
                signals=["official_release"],
            )
        )

    return rows


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, timeout=25)
        res.raise_for_status()
        rows = parse_hrp_html(res.text)
        if not rows:
            raise ValueError("HRP news page fetched but no dated police release cards were parsed")
        return rows

    return guarded_fetch(SOURCE, URL, "official", run, notes="Official HRP releases; useful for context/corroboration but often slower than dispatch feeds.")
