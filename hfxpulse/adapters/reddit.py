from __future__ import annotations

from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, iso_utc, keyword_hit, parse_datetime, stable_id

URL = "https://www.reddit.com/r/halifax/new/.rss"
SOURCE = "r/halifax community"
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}
KEYWORDS = (
    "sirens", "police", "fire", "ambulance", "smoke", "crash", "collision", "closed", "closure", "downtown",
    "barrington", "spring garden", "waterfront", "quinpool", "rob ie", "robie", "emergency", "evacu"
)


def _self_post_body(content_html: str) -> str:
    """Return only the user-authored self-post body, never feed author metadata."""
    if not content_html:
        return ""
    soup = BeautifulSoup(content_html, "html.parser")
    body = soup.select_one(".md")
    return clean_text(body.get_text(" ", strip=True)) if body else ""


def parse_atom(data: bytes | str) -> list[Incident]:
    root = ET.fromstring(data)
    rows: list[Incident] = []

    for entry in root.findall("a:entry", ATOM_NS):
        title = clean_text(entry.findtext("a:title", default="", namespaces=ATOM_NS))
        content_html = entry.findtext("a:content", default="", namespaces=ATOM_NS) or ""
        body = _self_post_body(content_html)
        if not keyword_hit(f"{title} {body}", KEYWORDS):
            continue

        published = clean_text(
            entry.findtext("a:published", default="", namespaces=ATOM_NS)
            or entry.findtext("a:updated", default="", namespaces=ATOM_NS)
        )
        reported = iso_utc(parse_datetime(published))
        if not reported:
            continue

        link_node = entry.find("a:link[@rel='alternate']", ATOM_NS) or entry.find("a:link", ATOM_NS)
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
        rows = parse_atom(res.content)
        return rows

    return guarded_fetch(
        SOURCE,
        URL,
        "community",
        run,
        notes="Unverified context only. Public subreddit Atom feed; community posts never upgrade an incident to confirmed status and author identities are not stored.",
    )
