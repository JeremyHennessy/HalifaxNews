from __future__ import annotations

import html as html_lib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from hfxpulse.adapters.base import AdapterResult, session
from hfxpulse.models import Incident, SourceHealth, utc_now_iso
from hfxpulse.util import clean_text, infer_category, infer_text_siren_score, iso_utc, parse_datetime, stable_id

# Geography and incident semantics are intentionally separate. A story should
# not enter the incident timeline merely because a Halifax publication mentions
# Halifax somewhere in otherwise unrelated copy.
LOCATION_TERMS = (
    "halifax", "dartmouth", "bedford", "hrm", "halifax regional municipality",
    "downtown halifax", "barrington", "spring garden", "lower water", "quinpool",
    "gottingen", "hollis", "argyle", "robie", "halifax harbour", "halifax waterfront",
    "macdonald bridge", "mackay bridge", "macdonald", "mackay",
)

INCIDENT_TERMS = (
    "siren", "sirens",
    "police", "rcmp", "officer", "officers", "search warrant", "arrest", "arrested",
    "firearm", "firearms", "gun", "guns", "weapon", "weapons", "shooting", "shots fired", "stabbing",
    "missing person", "missing child", "investigation",
    "fire", "fire crews", "fire department", "structure fire", "building fire", "house fire", "wildfire",
    "smoke", "flames", "blaze",
    "ambulance", "ehs", "paramedic", "paramedics", "medical emergency",
    "crash", "collision", "mvc", "rollover", "vehicle collision", "pedestrian struck",
    "road closure", "street closure", "lane closure", "closed", "closure", "traffic", "detour",
    "emergency", "evacuation", "evacuate", "shelter in place", "hazmat", "gas leak", "chemical spill",
    "rescue", "coast guard", "search and rescue", "person in water", "missing swimmer",
    "outage", "power outage", "without power", "water main", "water outage", "boil water", "water advisory",
    "flood", "flooding", "storm", "weather warning", "rainfall warning", "wind warning", "storm surge",
    "transit", "bus cancellation", "bus cancelled", "route cancelled", "route canceled", "service disruption",
    "ferry", "ferry cancellation", "ferry cancelled",
)


@dataclass(frozen=True)
class Feed:
    name: str
    url: str


FEEDS = (
    Feed("Global News Halifax", "https://globalnews.ca/halifax/feed/"),
    Feed("CBC Nova Scotia", "https://www.cbc.ca/webfeed/rss/rss-canada-novascotia"),
    Feed("CTV News Atlantic", "https://atlantic.ctvnews.ca/rss/ctv-news-atlantic-public-rss-1.822315"),
    Feed("Halifax Examiner", "https://www.halifaxexaminer.ca/feed/"),
    Feed("The Coast Halifax", "https://www.thecoast.ca/halifax/Rss.xml?section=957802"),
    Feed("CityNews Halifax", "https://halifax.citynews.ca/feed/"),
    Feed("Waterfront Media Halifax", "https://waterfrontmediahfx.the902hxir.ca/feed/"),
    Feed("Nova Scotia traffic advisories", "https://novascotia.ca/news/rss/traffic.asp"),
    Feed("Nova Scotia Emergency Management", "https://novascotia.ca/news/rss/rss.asp?dept=107"),
    Feed("Google News · Halifax emergency search", "https://news.google.com/rss/search?q=Halifax+Nova+Scotia+(fire+OR+police+OR+crash+OR+closure+OR+emergency+OR+sirens)&hl=en-CA&gl=CA&ceid=CA:en"),
    Feed("Bing News · Halifax emergency search", "https://www.bing.com/news/search?q=Halifax+Nova+Scotia+fire+police+crash+emergency+sirens&format=rss"),
)


def _strip_html(text: str | None) -> str:
    value = html_lib.unescape(text or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return clean_text(value)


def _term_hit(text: str, term: str) -> bool:
    """Match a term as a lexical token/phrase, not an arbitrary substring."""
    return bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, flags=re.I))


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(_term_hit(text, term) for term in terms)


def relevant_news_text(text: str) -> bool:
    return _has_any(text, LOCATION_TERMS) and _has_any(text, INCIDENT_TERMS)


def parse_feed(data: bytes, feed_name: str, feed_url: str) -> list[Incident]:
    root = ET.fromstring(data)
    rows: list[Incident] = []
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    for item in items:
        def text_for(*names: str) -> str:
            for name in names:
                node = item.find(name)
                if node is not None and node.text:
                    return clean_text(node.text)
            return ""

        title = text_for("title", "{http://www.w3.org/2005/Atom}title")
        desc = _strip_html(text_for("description", "summary", "{http://www.w3.org/2005/Atom}summary", "{http://purl.org/rss/1.0/modules/content/}encoded"))
        link = text_for("link")
        if not link:
            node = item.find("{http://www.w3.org/2005/Atom}link")
            if node is not None:
                link = clean_text(node.attrib.get("href"))
        when = text_for("pubDate", "published", "updated", "{http://www.w3.org/2005/Atom}published", "{http://www.w3.org/2005/Atom}updated")
        dt = parse_datetime(when)
        if not title or not dt:
            continue

        combined = f"{title} {desc}"
        if not relevant_news_text(combined):
            continue

        reported = iso_utc(dt) or ""
        category = infer_category(combined, "COMMUNITY")
        rows.append(Incident(
            id=f"news-{stable_id(feed_name, link, title)}",
            source=feed_name,
            source_url=link or feed_url,
            title=title,
            summary=desc[:650] or "News report.",
            category=category,
            subtype="news_report",
            reported_at=reported,
            source_kind="news",
            confidence="reported",
            severity=2 if category in {"FIRE", "RESCUE", "EMS", "POLICE", "EMERGENCY"} else 1,
            siren_score=infer_text_siren_score(combined, reported, "news"),
            signals=["news_report"],
            raw_ids=[link] if link else [],
        ))
    return rows


def fetch() -> AdapterResult:
    incidents: dict[str, Incident] = {}
    failures: list[str] = []
    successes = 0
    s = session()
    for feed in FEEDS:
        try:
            res = s.get(feed.url, timeout=20)
            res.raise_for_status()
            parsed = parse_feed(res.content, feed.name, feed.url)
            successes += 1
            incidents.update({row.id: row for row in parsed})
        except Exception as exc:
            failures.append(f"{feed.name}: {type(exc).__name__}: {exc}")
    status = "ok" if successes else "error"
    return AdapterResult(
        incidents=list(incidents.values()),
        health=SourceHealth(
            source="Local news & news search feeds",
            url="https://globalnews.ca/halifax/feed/",
            authority="news / aggregator",
            status=status,
            checked_at=utc_now_iso(),
            fetched_at=utc_now_iso() if successes else None,
            records=len(incidents),
            error="; ".join(failures[:3]) if failures and not successes else None,
            notes=(
                f"{successes}/{len(FEEDS)} feeds reachable. Items require both Halifax-area geography and a separate "
                "public-safety/disruption signal; reports are not treated as dispatch confirmation."
            ),
        ),
    )
