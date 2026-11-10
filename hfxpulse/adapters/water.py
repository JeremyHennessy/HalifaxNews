from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, iso_utc, parse_datetime, stable_id

URL = "https://www.halifaxwater.ca/notices-and-news"
SOURCE = "Halifax Water"


def parse_html(html: str) -> list[Incident]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Incident] = []
    seen: set[str] = set()
    # Teasers carry a publication time; archive rows carry a machine-readable
    # last-changed time. Keep each date inside its own card, never a page-wide
    # ancestor, and prefer the richer teaser when a notice appears in both.
    cards = [*soup.select("article"), *soup.select(".view__row, .views-row")]
    for card in cards:
        link = card.select_one("h2 a[href], .views-field-title a[href]")
        if link is None:
            continue
        title = clean_text(link.get_text(" ", strip=True))
        full = urljoin(URL, link.get("href", ""))
        parsed_url = urlparse(full)
        if (parsed_url.scheme != "https" or parsed_url.netloc != "www.halifaxwater.ca"
                or not parsed_url.path.startswith("/notice/") or len(title) < 10 or full in seen):
            continue
        published = card.select_one(".date-published .field-value")
        time_node = card.select_one("time[datetime]")
        if published is not None:
            raw_time = clean_text(published.get_text(" ", strip=True))
            timestamp_kind = "published"
            dt = parse_datetime(raw_time.replace("|", " "))
        elif time_node is not None:
            raw_time = time_node.get("datetime", "")
            timestamp_kind = "updated" if card.select_one(".views-field-changed") else "published"
            dt = parse_datetime(raw_time)
        else:
            continue
        if not dt:
            continue
        seen.add(full)
        body = card.select_one(".field--name-field-body")
        context = clean_text(body.get_text(" ", strip=True)) if body is not None else title
        lower = title.lower()
        rows.append(
            Incident(
                id=f"water-{stable_id(full)}",
                source=SOURCE,
                source_url=full,
                title=title,
                summary=context[:600],
                category="UTILITY",
                subtype="water_notice",
                reported_at=iso_utc(dt) or "",
                severity=2 if any(k in lower for k in ("emergency", "closure", "outage", "boil")) else 1,
                signals=["official_notice"],
                metadata={"source_timestamp_kind": timestamp_kind, "source_timestamp": raw_time},
            )
        )
    return rows


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, timeout=25)
        res.raise_for_status()
        rows = parse_html(res.text)
        if not rows:
            raise ValueError("Halifax Water page fetched but no dated notices were parsed")
        return rows

    return guarded_fetch(SOURCE, URL, "official", run, notes="Official dated notice cards. Source publication time is preserved; archive-only rows explicitly identify their last-updated timestamp.")
