from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import HALIFAX_TZ, clean_text, iso_utc, stable_id

URL = "https://downtownhalifax.ca/events"
SOURCE = "Downtown Halifax events"
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
DATE_RE = re.compile(rf"\b({MONTHS})\s+(\d{{1,2}})(?:\s*[-–]\s*(?:(?:{MONTHS})\s+)?(\d{{1,2}}))?(?:,?\s+(\d{{4}}))?", re.I)


def _month_num(name: str) -> int:
    return datetime.strptime(name[:3].title(), "%b").month


def _active_today(text: str, now: datetime) -> bool:
    m = DATE_RE.search(text)
    if not m:
        return False
    month = _month_num(m.group(1))
    start_day = int(m.group(2))
    end_day = int(m.group(3) or start_day)
    year = int(m.group(4) or now.year)
    if month != now.month or year != now.year:
        return False
    return start_day <= now.day <= end_day


def parse_html(html: str, now: datetime | None = None) -> list[Incident]:
    now = now or datetime.now(HALIFAX_TZ)
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Incident] = []
    seen: set[str] = set()
    for link in soup.select("a[href]"):
        title = clean_text(link.get_text(" ", strip=True))
        if len(title) < 4:
            continue
        container = link.find_parent(["article", "li", "div"]) or link.parent
        context = clean_text(container.get_text(" ", strip=True) if container else title)
        if not _active_today(context, now):
            continue
        full = urljoin(URL, link.get("href", ""))
        key = stable_id(full, title)
        if key in seen:
            continue
        seen.add(key)
        rows.append(Incident(
            id=f"dhevent-{key}",
            source=SOURCE,
            source_url=full or URL,
            title=title,
            summary=context[:650],
            category="EVENT",
            subtype="downtown_event",
            reported_at=iso_utc(now) or "",
            source_kind="event",
            confidence="listing",
            location_text="Downtown Halifax",
            severity=0,
            siren_score=0,
            signals=["event_context"],
        ))
    return rows[:40]


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, timeout=25)
        res.raise_for_status()
        return parse_html(res.text)
    return guarded_fetch(SOURCE, URL, "event listing", run, notes="Only events whose published date range includes today are emitted as context.")
