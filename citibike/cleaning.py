from datetime import datetime, timedelta, timezone
from functools import lru_cache
import math
import re
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
POLICY_VERSION = 1
RIDE_ID_RE = re.compile(r"[0-9A-F]{16}")
VALID_USERS = {"member", "casual"}
VALID_BIKES = {"classic_bike", "electric_bike", "docked_bike"}
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


@lru_cache(maxsize=16384)
def _ny_utc_offset(year, month, day, hour):
    probe = datetime(year, month, day, hour, 0, 0)
    first = probe.replace(tzinfo=NY, fold=0).utcoffset()
    second = probe.replace(tzinfo=NY, fold=1).utcoffset()
    if first != second:
        return None
    return first


def local_to_utc(text):
    local = datetime.fromisoformat(text)
    if local.tzinfo is not None:
        raise ValueError("Oczekiwano czasu lokalnego bez offsetu")
    offset = _ny_utc_offset(local.year, local.month, local.day, local.hour)
    if offset is None:
        raise ValueError("Niejednoznaczna godzina podczas zmiany czasu (DST)")
    return local, (local - offset).replace(tzinfo=timezone.utc)


def coordinate(value, bound):
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    number = float(stripped)
    if not math.isfinite(number) or not -bound <= number <= bound:
        raise ValueError("Współrzędna poza zakresem")
    return number


def clean_row(row):
    if None in row or any(row.get(key) is None for key in REQUIRED_COLUMNS):
        return None, "niepoprawna_liczba_pol"
    ride_id = row["ride_id"].strip().upper()
    if not RIDE_ID_RE.fullmatch(ride_id):
        return None, "niepoprawny_id"
    user = row["member_casual"].strip().lower()
    bike = row["rideable_type"].strip().lower()
    if user not in VALID_USERS or bike not in VALID_BIKES:
        return None, "nieznana_kategoria"
    started_at_local = row["started_at"].strip()
    ended_at_local = row["ended_at"].strip()
    try:
        start_local, start = local_to_utc(started_at_local)
        _, end = local_to_utc(ended_at_local)
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
        start_lat = coordinate(row["start_lat"], 90)
        start_lng = coordinate(row["start_lng"], 180)
        end_lat = coordinate(row["end_lat"], 90)
        end_lng = coordinate(row["end_lng"], 180)
    except ValueError:
        return None, "niepoprawne_wspolrzedne"
    return {
        "_id": ride_id,
        "rideable_type": bike,
        "started_at": start,
        "ended_at": end,
        "started_at_local": started_at_local,
        "ended_at_local": ended_at_local,
        "member_casual": user,
        "duration_seconds": duration,
        "start_hour": start_local.hour,
        "start_weekday": start_local.weekday(),
        "start_month": start_local.month,
        "start_lat": start_lat,
        "start_lng": start_lng,
        "end_lat": end_lat,
        "end_lng": end_lng,
        "start_station_id": row["start_station_id"].strip() or None,
        "start_station_name": row["start_station_name"].strip() or None,
        "end_station_id": row["end_station_id"].strip() or None,
        "end_station_name": row["end_station_name"].strip() or None,
    }, None

