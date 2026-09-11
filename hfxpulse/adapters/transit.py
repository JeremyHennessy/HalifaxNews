from __future__ import annotations

from datetime import datetime, timezone

from hfxpulse.adapters.base import AdapterResult, guarded_fetch, session
from hfxpulse.models import Incident
from hfxpulse.util import clean_text, stable_id

URL = "https://gtfs.halifax.ca/realtime/Alert/Alerts.pb"
SOURCE = "Halifax Transit GTFS-Realtime"


def _translation_text(translated) -> str:
    for item in translated.translation:
        if getattr(item, "language", "") in ("en", "en-CA", ""):
            return clean_text(item.text)
    return clean_text(translated.translation[0].text) if translated.translation else ""


def parse_feed(data: bytes) -> list[Incident]:
    # Imported lazily so a missing optional decoder degrades only this source.
    from google.transit import gtfs_realtime_pb2
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(data)
    rows: list[Incident] = []
    header_ts = int(feed.header.timestamp) if feed.header.timestamp else int(datetime.now(timezone.utc).timestamp())
    for entity in feed.entity:
        if not entity.HasField("alert"):
            continue
        alert = entity.alert
        header = _translation_text(alert.header_text) or "Halifax Transit service alert"
        description = _translation_text(alert.description_text)
        if alert.active_period:
            start = alert.active_period[0].start or header_ts
        else:
            start = header_ts
        reported = datetime.fromtimestamp(start, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        informed = []
        for ie in alert.informed_entity:
            bits = []
            if ie.route_id:
                bits.append(f"route {ie.route_id}")
            if ie.stop_id:
                bits.append(f"stop {ie.stop_id}")
            if bits:
                informed.append(" / ".join(bits))
        rows.append(
            Incident(
                id=f"transit-{stable_id(entity.id, header, start)}",
                source=SOURCE,
                source_url="https://www.halifax.ca/transportation/halifax-transit/service-disruptions",
                title=header,
                summary=description or (", ".join(informed[:8]) if informed else "Transit service alert"),
                category="TRANSIT",
                subtype="gtfs_realtime_alert",
                reported_at=reported,
                severity=2,
                signals=["official_realtime_feed"],
                raw_ids=[entity.id] if entity.id else [],
                metadata={"informed_entities": informed[:50]},
            )
        )
    return rows


def fetch() -> AdapterResult:
    def run() -> list[Incident]:
        res = session().get(URL, timeout=20)
        res.raise_for_status()
        return parse_feed(res.content)

    return guarded_fetch(SOURCE, URL, "official", run, notes="Official GTFS-Realtime alerts; data licensed under the Open Government Licence — Halifax.")
