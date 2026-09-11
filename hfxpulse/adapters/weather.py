from __future__ import annotations

import xml.etree.ElementTree as ET

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, iso_utc, parse_datetime, stable_id

URL = "https://weather.gc.ca/rss/battleboard/ns1_e.xml"
SOURCE = "Environment and Climate Change Canada"
ATOM = "{http://www.w3.org/2005/Atom}"


def _text(node, tag: str) -> str:
    child = node.find(ATOM + tag)
    return clean_text(child.text if child is not None else "")


def parse_atom(data: bytes) -> list[Incident]:
    root = ET.fromstring(data)
    rows: list[Incident] = []
    for item in root.findall(ATOM + "entry"):
        title = _text(item, "title") or "Weather alert"
        summary = _text(item, "summary") or _text(item, "content")
        when = _text(item, "updated") or _text(item, "published")
        dt = parse_datetime(when)
        if not dt:
            continue
        link_node = item.find(ATOM + "link")
        link = link_node.attrib.get("href", URL) if link_node is not None else URL
        item_id = _text(item, "id")
        inactive = any(x in title.lower() for x in ("ended", "cancelled", "canceled"))
        rows.append(
            Incident(
                id=f"eccc-{stable_id(item_id, title, when)}",
                source=SOURCE,
                source_url=link,
                title=title,
                summary=summary[:700],
                category="WEATHER",
                subtype="public_alert",
                reported_at=iso_utc(dt) or "",
                status="resolved" if inactive else "active",
                severity=2 if not inactive else 1,
                signals=["official_alert"],
            )
        )
    return rows


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, timeout=20)
        res.raise_for_status()
        return parse_atom(res.content)

    return guarded_fetch(SOURCE, URL, "official", run, notes="Halifax Metro and Halifax County West near-real-time public weather alert Atom feed.")
