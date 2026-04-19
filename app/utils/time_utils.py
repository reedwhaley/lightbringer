from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


TIMEZONE_ALIASES = {
    # Core
    "UTC": "UTC",
    "GMT": "Europe/London",

    # North America
    "ET": "America/New_York",
    "EST": "America/New_York",
    "EDT": "America/New_York",

    "CT": "America/Chicago",
    "CST": "America/Chicago",
    "CDT": "America/Chicago",

    "MT": "America/Denver",
    "MST": "America/Denver",
    "MDT": "America/Denver",

    "PT": "America/Los_Angeles",
    "PST": "America/Los_Angeles",
    "PDT": "America/Los_Angeles",

    "AKT": "America/Anchorage",
    "AKST": "America/Anchorage",
    "AKDT": "America/Anchorage",

    "HST": "Pacific/Honolulu",

    # Europe
    "BST": "Europe/London",
    "WET": "Europe/Lisbon",
    "WEST": "Europe/Lisbon",

    "CET": "Europe/Paris",
    "CEST": "Europe/Paris",

    "EET": "Europe/Helsinki",
    "EEST": "Europe/Helsinki",

    # Asia
    "IST": "Asia/Kolkata",
    "JST": "Asia/Tokyo",
    "KST": "Asia/Seoul",
    "SGT": "Asia/Singapore",
    "HKT": "Asia/Hong_Kong",

    # Australia / NZ
    "AEST": "Australia/Sydney",
    "AEDT": "Australia/Sydney",
    "ACST": "Australia/Adelaide",
    "ACDT": "Australia/Adelaide",
    "AWST": "Australia/Perth",

    "NZST": "Pacific/Auckland",
    "NZDT": "Pacific/Auckland",
}


def normalize_timezone_name(value: str) -> str:
    cleaned = value.strip()
    return TIMEZONE_ALIASES.get(cleaned.upper(), cleaned)


def get_zoneinfo(timezone_name: str) -> ZoneInfo:
    normalized = normalize_timezone_name(timezone_name)
    return ZoneInfo(normalized)


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_local_datetime_input(value: str) -> str:
    """
    Accepts:
      YYYY-MM-DD HH:MM
      YYYY-MM-DD HHMM
      YYYY-MM-DD HMM

    Returns normalized:
      YYYY-MM-DD HH:MM
    """
    raw = " ".join(str(value or "").strip().split())
    parts = raw.split(" ")

    if len(parts) != 2:
        return raw

    date_part, time_part = parts

    if ":" in time_part:
        return raw

    if not time_part.isdigit():
        return raw

    if len(time_part) == 3:
        time_part = f"0{time_part}"

    if len(time_part) == 4:
        return f"{date_part} {time_part[:2]}:{time_part[2:]}"

    return raw


def parse_local_time_to_utc(start_local: str, timezone_name: str) -> datetime:
    """
    Parse local naive datetime string in format:
      YYYY-MM-DD HH:MM
      YYYY-MM-DD HHMM
      YYYY-MM-DD HMM

    and convert it to UTC.
    """
    normalized_input = _normalize_local_datetime_input(start_local)
    naive = datetime.strptime(normalized_input.strip(), "%Y-%m-%d %H:%M")
    tz = get_zoneinfo(timezone_name)
    local_dt = naive.replace(tzinfo=tz)
    return local_dt.astimezone(timezone.utc)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_to_local_display(
    dt: datetime,
    timezone_name: str,
    fmt: str = "%Y-%m-%d %I:%M %p %Z",
) -> str:
    dt = ensure_utc(dt)
    tz = get_zoneinfo(timezone_name)
    return dt.astimezone(tz).strftime(fmt)


def discord_timestamp(dt: datetime, style: str = "F") -> str:
    dt = ensure_utc(dt)
    unix_ts = int(dt.timestamp())
    return f"<t:{unix_ts}:{style}>"


def compute_windows(
    start_at_utc: datetime,
    setup_minutes: int = 30,
    seed_prompt_minutes: int = 20,
) -> tuple[datetime, datetime, datetime]:
    """
    Returns:
      setup_at_utc,
      room_open_at_utc,
      seed_prompt_at_utc
    """
    start_at_utc = ensure_utc(start_at_utc)

    setup_at_utc = start_at_utc - timedelta(minutes=setup_minutes)
    room_open_at_utc = start_at_utc - timedelta(minutes=30)
    seed_prompt_at_utc = start_at_utc - timedelta(minutes=seed_prompt_minutes)

    return setup_at_utc, room_open_at_utc, seed_prompt_at_utc