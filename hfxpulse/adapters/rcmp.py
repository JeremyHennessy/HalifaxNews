from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, infer_text_siren_score, iso_utc, keyword_hit, parse_datetime, stable_id

URL = "https://rcmp.ca/en/nova-scotia/news"
SOURCE = "RCMP Nova Scotia"
AREA_TERMS = ("halifax", "dartmouth", "bedford", "sackville", "cole harbour", "tantallon", "timberlea", "hrm", "halifax regional")


def parse_html(html: str) -> list[Incident]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Incident] = []
    seen: set[str] = set()
    for link in soup.select("a[href]"):
        title = clean_text(link.get_text(" ", strip=True))
        href = link.get("href") or ""
        if len(title) < 12 or "/news/" not in href:
            continue
        full = urljoin(URL, href)
        if full in seen:
            continue
        container = link.find_parent(["article", "li", "div"]) or link.parent
        context = clean_text(container.get_text(" ", strip=True) if container else title)
        if not keyword_hit(f"{title} {context}", AREA_TERMS):
            continue
        m = re.search(r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}(?:,?\s+\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?)?)?", context, re.I)
        dt = parse_datetime(m.group(0)) if m else None
        if not dt:
            continue
        seen.add(full)
        reported = iso_utc(dt) or ""
        rows.append(Incident(
            id=f"rcmp-{stable_id(full)}",
            source=SOURCE,
            source_url=full,
            title=title,
            summary=context[:650],
            category="POLICE",
            subtype="police_release",
            reported_at=reported,
            source_kind="official",
            confidence="official",
            severity=2,
            siren_score=infer_text_siren_score(f"{title} {context}", reported, "official"),
            signals=["official_release"],
        ))
    return rows


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, timeout=25)
        res.raise_for_status()
        return parse_html(res.text)
    return guarded_fetch(SOURCE, URL, "official", run, notes="RCMP Nova Scotia releases filtered to HRM-area place names.")
