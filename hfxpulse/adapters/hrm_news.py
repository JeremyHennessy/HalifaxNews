from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, infer_category, infer_text_siren_score, iso_utc, parse_datetime, stable_id

URL = "https://www.halifax.ca/home/news"
SOURCE = "HRM newsroom"
TERMS = (
    "police", "fire", "emergency", "traffic", "road closure", "road closed", "collision", "weapons", "shooting",
    "stabbing", "missing", "evacuation", "hazmat", "transit", "ferry", "bridge", "flood", "storm", "power",
    "water", "shelter in place", "public safety", "crash", "explosion",
)
POSTED_RE = re.compile(r"Posted:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4}\s*-\s*\d{1,2}:\d{2}\s*(?:am|pm))", re.I)


def parse_html(html: str) -> list[Incident]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Incident] = []
    # Drupal view rows are the most stable structure; fallback to article-like containers.
    candidates = soup.select(".views-row, article")
    if not candidates:
        candidates = soup.select("main li, main .field-content")
    for node in candidates:
        text = clean_text(node.get_text(" ", strip=True))
        lower = text.lower()
        if len(text) < 25 or not any(term in lower for term in TERMS):
            continue
        posted = POSTED_RE.search(text)
        dt = parse_datetime(posted.group(1).replace(" - ", " ")) if posted else None
        if not dt:
            # Try <time datetime> if the current Drupal markup supplies one.
            time_node = node.find("time")
            dt = parse_datetime(time_node.get("datetime") if time_node else None)
        if not dt:
            continue
        link = node.find("a", href=True)
        title = clean_text(link.get_text(" ", strip=True) if link else "")
        if len(title) < 5:
            # Remove posted prefix and use the first sentence as a conservative title.
            title = re.sub(r"^Posted:\s*[^A-Z]+", "", text, flags=re.I)[:160] or "HRM public notice"
        full = urljoin(URL, link.get("href", "")) if link else URL
        reported = iso_utc(dt) or ""
        category = infer_category(text, "EMERGENCY")
        rows.append(Incident(
            id=f"hrm-news-{stable_id(full, title, reported)}",
            source=SOURCE,
            source_url=full,
            title=title,
            summary=text[:700],
            category=category,
            subtype="municipal_newsroom",
            reported_at=reported,
            source_kind="official",
            confidence="official",
            severity=2 if category in {"FIRE", "RESCUE", "EMS", "POLICE", "EMERGENCY"} else 1,
            siren_score=infer_text_siren_score(text, reported, "official"),
            signals=["municipal_newsroom"],
        ))
    return list({r.id: r for r in rows}.values())[:80]


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, params={"page": 0}, timeout=25)
        res.raise_for_status()
        return parse_html(res.text)
    return guarded_fetch(SOURCE, URL, "official", run, notes="Current HRM newsroom filtered to public-safety, transportation and disruption terms.")
