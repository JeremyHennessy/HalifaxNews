from __future__ import annotations

from datetime import datetime, timezone

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, infer_text_siren_score, keyword_hit, stable_id

URL = "https://halifaxharbourbridges.ca/traffic/"
SOURCE = "Halifax Harbour Bridges"
ALERT_TERMS = ("closed", "closure", "incident", "collision", "delay", "restricted", "maintenance", "lane", "emergency", "heavy traffic")


def parse_html(html: str) -> list[Incident]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[Incident] = []
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    candidates = []
    for node in soup.select("article, .alert, .notice, .traffic, .content, main p, main li"):
        text = clean_text(node.get_text(" ", strip=True))
        if 18 <= len(text) <= 900 and keyword_hit(text, ALERT_TERMS) and keyword_hit(text, ("bridge", "Macdonald", "MacKay", "lane", "traffic")):
            candidates.append(text)
    for text in dict.fromkeys(candidates):
        title = text[:140] + ("…" if len(text) > 140 else "")
        lower = text.lower()
        if not any(term in lower for term in ("closed", "closure", "incident", "collision", "delay", "restricted", "emergency", "heavy traffic")):
            continue
        rows.append(Incident(
            id=f"bridge-{stable_id(text)}",
            source=SOURCE,
            source_url=URL,
            title=title,
            summary=text,
            category="TRAFFIC",
            subtype="bridge_status",
            reported_at=now,
            source_kind="official",
            confidence="official",
            severity=2 if any(k in lower for k in ("closed", "closure", "incident", "collision", "emergency")) else 1,
            siren_score=infer_text_siren_score(text, now, "official"),
            signals=["bridge_status"],
        ))
    return rows[:20]


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, timeout=25)
        res.raise_for_status()
        return parse_html(res.text)
    return guarded_fetch(SOURCE, URL, "official", run, notes="Live bridge traffic/closure page. Only disruption-like text is emitted into the incident timeline.")
