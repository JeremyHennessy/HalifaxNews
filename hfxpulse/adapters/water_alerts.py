from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, iso_utc, parse_datetime, stable_id

URL = "https://www.halifaxwater.ca/alerts"
SOURCE = "Halifax Water active alerts"

DATE_RE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}",
    re.I,
)
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\s*(?:AM|PM)\b", re.I)


def _reported_at(text: str) -> str | None:
    # Prefer the most recent explicit update; otherwise use the published date.
    updates = list(re.finditer(r"Updated:\s*([^|]+)\|\s*([^\n]+)", text, re.I))
    if updates:
        chunk = " ".join(updates[-1].groups())
        dt = parse_datetime(chunk)
        if dt:
            return iso_utc(dt)
    date_matches = DATE_RE.findall(text)
    if not date_matches:
        return None
    time_match = TIME_RE.search(text)
    chunk = f"{date_matches[-1]} {time_match.group(0) if time_match else ''}".strip()
    return iso_utc(parse_datetime(chunk))


def parse_html(html: str) -> list[Incident]:
    # The current page places active alerts above the "View Past Alerts" boundary.
    # Split there so historical alert links never become permanently-active rows.
    boundary = re.search(r"View\s+Past\s+Alerts", html, re.I)
    active_html = html[: boundary.start()] if boundary else html
    soup = BeautifulSoup(active_html, "html.parser")
    rows: list[Incident] = []
    seen: set[str] = set()

    for link in soup.select('a[href*="/alert/"]'):
        title = clean_text(link.get_text(" ", strip=True))
        href = clean_text(link.get("href", ""))
        if not title or not href:
            continue
        full = urljoin(URL, href)
        if full in seen:
            continue
        seen.add(full)
        container = link.find_parent(["article", "li", "div", "section"]) or link.parent
        context = clean_text(container.get_text(" ", strip=True) if container else title)
        reported = _reported_at(context)
        if not reported:
            # Active status is still useful even when the listing omits its timestamp.
            # The fetch layer will supply observation time only for such rows.
            continue
        lower = f"{title} {context}".lower()
        subtype = "boil_water_advisory" if "boil water" in lower else "water_alert"
        rows.append(Incident(
            id=f"water-alert-{stable_id(full, title)}",
            source=SOURCE,
            source_url=full,
            title=title,
            summary=context[:700],
            category="UTILITY",
            subtype=subtype,
            reported_at=reported,
            source_kind="official",
            confidence="official",
            severity=3 if any(term in lower for term in ("boil water", "do not consume", "emergency")) else 2,
            signals=["official_active_alert"],
            metadata={"currently_active": True},
        ))
    return rows


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, timeout=25)
        res.raise_for_status()
        return parse_html(res.text)

    return guarded_fetch(
        SOURCE,
        URL,
        "official",
        run,
        notes="Current Halifax Water alert banner/list; historical alerts are excluded at the parser boundary.",
    )
