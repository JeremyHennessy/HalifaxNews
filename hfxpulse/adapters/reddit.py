from __future__ import annotations

from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, iso_utc, parse_datetime, stable_id

URL = "https://www.reddit.com/r/halifax/new/.rss"
SOURCE = "r/halifax community"
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}

# Community data is deliberately high-precision rather than exhaustive. A location
# word by itself (for example "downtown") must never turn an ordinary post into an
# incident signal.
SIGNAL_TERMS = (
    "sirens", "police", "fire truck", "fire trucks", "fire department", "structure fire", "smoke",
    "ambulance", "paramedic", "crash", "collision", "accident", "emergency", "evacu", "explosion",
    "shooting", "stabbing", "swat", "hazmat", "rescue", "road closed", "road closure", "street closed",
    "bridge closed", "blocked off", "power outage", "outage",
)
QUESTION_TERMS = (
    "what happened", "what's happening", "what is happening", "what's going on", "what is going on",
    "anyone know", "does anyone know", "why are there", "what was that",
)
LOCATION_TERMS = (
    "downtown", "barrington", "spring garden", "waterfront", "quinpool", "robie", "gottingen", "hollis",
    "lower water", "upper water", "brunswick", "citadel", "argyle", "sackville st", "south end", "north end",
)


def _self_post_body(content_html: str) -> str:
    """Return only the user-authored self-post body, never feed author metadata."""
    if not content_html:
        return ""
    soup = BeautifulSoup(content_html, "html.parser")
    body = soup.select_one(".md")
    return clean_text(body.get_text(" ", strip=True)) if body else ""


def _incident_hit(text: str) -> bool:
    value = text.lower()
    if any(term in value for term in SIGNAL_TERMS):
        return True
    return any(term in value for term in QUESTION_TERMS) and any(term in value for term in LOCATION_TERMS)


def parse_atom(data: bytes | str) -> list[Incident]:
    root = ET.fromstring(data)
    rows: list[Incident] = []

    for entry in root.findall("a:entry", ATOM_NS):
        title = clean_text(entry.findtext("a:title", default="", namespaces=ATOM_NS))
        content_html = entry.findtext("a:content", default="", namespaces=ATOM_NS) or ""
        body = _self_post_body(content_html)
        if not _incident_hit(f"{title} {body}"):
            continue

        published = clean_text(
            entry.findtext("a:published", default="", namespaces=ATOM_NS)
            or entry.findtext("a:updated", default="", namespaces=ATOM_NS)
        )
        reported = iso_utc(parse_datetime(published))
        if not reported:
            continue

        link_node = entry.find("a:link[@rel='alternate']", ATOM_NS)
        if link_node is None:
            link_node = entry.find("a:link", ATOM_NS)
        href = clean_text(link_node.get("href", "") if link_node is not None else "")
        if not href.startswith("https://www.reddit.com/r/halifax/comments/"):
            continue

        entry_id = clean_text(entry.findtext("a:id", default="", namespaces=ATOM_NS))
        raw_id = entry_id.removeprefix("t3_") if entry_id else ""
        if not raw_id:
            raw_id = stable_id(href)

        rows.append(
            Incident(
                # Preserve the identifier shape used by the former JSON adapter.
                id=f"reddit-{stable_id(raw_id, title)}",
                source=SOURCE,
                source_url=href,
                title=title,
                summary=body[:350] if body else "Community report — not independently verified.",
                category="COMMUNITY",
                subtype="community_report",
                reported_at=reported,
                source_kind="community",
                confidence="unverified",
                severity=1,
                signals=["community_report", "unverified"],
                raw_ids=[raw_id],
                # Author identity is intentionally not read or persisted.
                metadata={},
            )
        )

    return rows


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(
            URL,
            timeout=20,
            headers={"Accept": "application/atom+xml, application/rss+xml, text/xml;q=0.9"},
        )
        res.raise_for_status()
        return parse_atom(res.content)

    return guarded_fetch(
        SOURCE,
        URL,
        "community",
        run,
        notes="Unverified context only. Public subreddit Atom feed; community posts never upgrade an incident to confirmed status and author identities are not stored.",
    )
