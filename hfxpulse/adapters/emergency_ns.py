from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, iso_utc, parse_datetime, stable_id

URL = "https://emergencyinfo.novascotia.ca/"
SOURCE = "Emergency Info Nova Scotia"


def parse_html(html: str) -> list[Incident]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Incident] = []
    seen: set[str] = set()
    heading = soup.find(lambda t: t.name in {"h1","h2","h3"} and "current active events" in clean_text(t.get_text()).lower())
    root = heading.parent if heading else soup
    for link in root.select("a[href]"):
        title = clean_text(link.get_text(" ", strip=True))
        href = link.get("href", "")
        if len(title) < 6 or href.startswith("#"):
            continue
        full = urljoin(URL, href)
        if full in seen or full.rstrip("/") == URL.rstrip("/"):
            continue
        container = link.find_parent(["article", "li", "div"]) or link.parent
        context = clean_text(container.get_text(" ", strip=True) if container else title)
        # Avoid preparedness/nav content when markup is broad.
        if not any(k in context.lower() for k in ("active", "evac", "wildfire", "flood", "storm", "emergency", "order", "alert")):
            continue
        m = re.search(r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December),?\s+\d{4}\b", context, re.I)
        dt = parse_datetime(m.group(0)) if m else None
        # Active-event cards sometimes provide only a date; keep it as source time.
        reported = iso_utc(dt) if dt else None
        if not reported:
            continue
        seen.add(full)
        rows.append(
            Incident(
                id=f"nsemergency-{stable_id(full, title)}",
                source=SOURCE,
                source_url=full,
                title=title,
                summary=context[:650],
                category="EMERGENCY",
                subtype="active_event",
                reported_at=reported,
                severity=3,
                signals=["official_active_event"],
            )
        )
    return rows


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, timeout=25)
        res.raise_for_status()
        return parse_html(res.text)

    return guarded_fetch(SOURCE, URL, "official", run, notes="Provincial active emergency events. Event dates can be less granular than dispatch sources.")
