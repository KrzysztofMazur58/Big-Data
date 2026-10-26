from datetime import datetime, timezone
import math
import re
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
POLICY_VERSION = 1
REQUIRED_COLUMNS = {
    "ride_id",
    "rideable_type",
    "started_at",
    "ended_at",
    "start_station_name",
    "start_station_id",
    "end_station_name",
    "end_station_id",
    "start_lat",
    "start_lng",
    "end_lat",
    "end_lng",
    "member_casual",
}


def local_to_utc(text):
    local = datetime.fromisoformat(text)
    if local.tzinfo is not None:
        raise ValueError("Oczekiwano czasu lokalnego bez offsetu")
    first = local.replace(tzinfo=NY, fold=0)
    second = local.replace(tzinfo=NY, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise ValueError("Niejednoznaczna godzina podczas zmiany czasu (DST)")
    return local, first.astimezone(timezone.utc)


def coordinate(value, bound):
    if value is None or not value.strip():
        return None
    number = float(value)
    if not math.isfinite(number) or not -bound <= number <= bound:
        raise ValueError("Współrzędna poza zakresem")
    return number


def clean_row(row):
    if None in row or any(row.get(key) is None for key in REQUIRED_COLUMNS):
        return None, "niepoprawna_liczba_pol"
    ride_id = row["ride_id"].strip().upper()
    if not re.fullmatch(r"[0-9A-F]{16}", ride_id):
        return None, "niepoprawny_id"
    user = row["member_casual"].strip().lower()
    bike = row["rideable_type"].strip().lower()
    if user not in {"member", "casual"} or bike not in {"classic_bike", "electric_bike", "docked_bike"}:
        return None, "nieznana_kategoria"
    try:
        start_local, start = local_to_utc(row["started_at"].strip())
        _, end = local_to_utc(row["ended_at"].strip())
    except (ValueError, OverflowError):
        return None, "niepoprawny_lub_niejednoznaczny_czas"
    if start_local.year != 2023:
        return None, "poza_rokiem_2023"
    duration = (end - start).total_seconds()
    if duration <= 0:
        return None, "czas_niedodatni"
    if duration > 86400:
        return None, "czas_ponad_24h"
    try:
        coords = {
            key: coordinate(row[key], 90 if key.endswith("lat") else 180)
            for key in ("start_lat", "start_lng", "end_lat", "end_lng")
        }
    except ValueError:
        return None, "niepoprawne_wspolrzedne"
    doc = {
        "_id": ride_id,
        "rideable_type": bike,
        "started_at": start,
        "ended_at": end,
        "started_at_local": row["started_at"].strip(),
        "ended_at_local": row["ended_at"].strip(),
        "member_casual": user,
        "duration_seconds": duration,
        "start_hour": start_local.hour,
        "start_weekday": start_local.weekday(),
        "start_month": start_local.month,
        **coords,
    }
    for key in ("start_station_id", "start_station_name", "end_station_id", "end_station_name"):
        doc[key] = row[key].strip() or None
    return doc, None

