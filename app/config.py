from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class RacetimeCategoryConfig:
    slug: str
    display_name: str
    client_id: str
    client_secret: str
    calendar_id: str
    weekly_calendar_id: str
    default_goal: str = "tournament"

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)


@dataclass(frozen=True)
class Settings:
    discord_token: str
    application_id: int
    guild_id: int
    claim_channel_id: int
    reminder_channel_id: int
    admin_channel_id: int
    player_alert_channel_id: int
    fallback_role_id: int
    allowed_role_ids: list[int]

    tournament_participant_role_id: int
    tournament_admin_role_id: int
    server_admin_role_id: int

    weekly_reminder_channel_id: int
    weekly_room_open_channel_id: int
    weekly_allowed_role_ids: list[int]
    weekly_ping_role_ids: dict[str, int]

    completed_matches_thread_id: int
    cancelled_matches_thread_id: int
    lightbringer_logs_thread_id: int

    olir_api_base_url: str
    olir_internal_api_token: str

    sg_base_url: str
    sg_sessionid: str
    sg_csrftoken: str
    sg_user_agent: str

    default_timezone: str
    database_url: str
    google_client_id: str
    google_client_secret: str
    google_refresh_token: str
    racetime_categories: dict[str, RacetimeCategoryConfig]

    twitch_client_id: str
    twitch_client_secret: str


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

def _optional(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()

def _parse_role_list(name: str) -> list[int]:
    return [int(x.strip()) for x in _required(name).split(",") if x.strip()]


def get_settings() -> Settings:
    categories = {
        "mpr": RacetimeCategoryConfig(
            slug="mpr",
            display_name="Metroid Prime",
            client_id=os.getenv("RACETIME_MPR_CLIENT_ID", "").strip(),
            client_secret=os.getenv("RACETIME_MPR_CLIENT_SECRET", "").strip(),
            calendar_id=_required("GOOGLE_MPR_CALENDAR_ID"),
            weekly_calendar_id=_required("GOOGLE_MPR_WEEKLY_CALENDAR_ID"),
            default_goal="tournament",
        ),
        "mp2r": RacetimeCategoryConfig(
            slug="mp2r",
            display_name="Metroid Prime 2",
            client_id=os.getenv("RACETIME_MP2R_CLIENT_ID", "").strip(),
            client_secret=os.getenv("RACETIME_MP2R_CLIENT_SECRET", "").strip(),
            calendar_id=_required("GOOGLE_MP2R_CALENDAR_ID"),
            weekly_calendar_id=_required("GOOGLE_MP2R_WEEKLY_CALENDAR_ID"),
            default_goal="tournament",
        ),
        "mpcgr": RacetimeCategoryConfig(
            slug="mpcgr",
            display_name="Metroid Prime CGC",
            client_id=os.getenv("RACETIME_MPCGR_CLIENT_ID", "").strip(),
            client_secret=os.getenv("RACETIME_MPCGR_CLIENT_SECRET", "").strip(),
            calendar_id=_required("GOOGLE_MPCGR_CALENDAR_ID"),
            weekly_calendar_id=_required("GOOGLE_MPCGR_WEEKLY_CALENDAR_ID"),
            default_goal="tournament",
        ),
    }

    return Settings(
        discord_token=_required("DISCORD_TOKEN"),
        application_id=int(_required("DISCORD_APPLICATION_ID")),
        guild_id=int(_required("GUILD_ID")),
        claim_channel_id=int(_required("CLAIM_CHANNEL_ID")),
        reminder_channel_id=int(_required("REMINDER_CHANNEL_ID")),
        admin_channel_id=int(_required("ADMIN_CHANNEL_ID")),
        player_alert_channel_id=int(_required("PLAYER_ALERT_CHANNEL_ID")),
        fallback_role_id=int(_required("FALLBACK_ROLE_ID")),
        allowed_role_ids=_parse_role_list("ALLOWED_ROLE_IDS"),
        tournament_participant_role_id=int(_required("TOURNAMENT_PARTICIPANT_ROLE_ID")),
        tournament_admin_role_id=int(_required("TOURNAMENT_ADMIN_ROLE_ID")),
        server_admin_role_id=int(_required("SERVER_ADMIN_ROLE_ID")),
        weekly_reminder_channel_id=int(_required("WEEKLY_REMINDER_CHANNEL_ID")),
        weekly_room_open_channel_id=int(_required("WEEKLY_ROOM_OPEN_CHANNEL_ID")),
        weekly_allowed_role_ids=_parse_role_list("WEEKLY_ALLOWED_ROLE_IDS"),
        weekly_ping_role_ids={
            "mpr": int(_required("WEEKLY_MPR_ROLE_ID")),
            "mp2r": int(_required("WEEKLY_MP2R_ROLE_ID")),
            "mpcgr": int(_required("WEEKLY_MPCGR_ROLE_ID")),
        },
        completed_matches_thread_id=int(_required("COMPLETED_MATCHES_THREAD_ID")),
        cancelled_matches_thread_id=int(_required("CANCELLED_MATCHES_THREAD_ID")),
        lightbringer_logs_thread_id=int(_required("LIGHTBRINGER_LOGS_THREAD_ID")),
        olir_api_base_url=_required("OLIR_API_BASE_URL").rstrip("/"),
        olir_internal_api_token=_required("OLIR_INTERNAL_API_TOKEN"),
        sg_base_url=os.getenv("SG_BASE_URL", "https://speedgaming.org").strip(),
        sg_sessionid=_optional("SG_SESSIONID", ""),
        sg_csrftoken=_optional("SG_CSRFTOKEN", ""),
        sg_user_agent=os.getenv("SG_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 OPR/129.0.0.0").strip(),
        default_timezone=os.getenv("DEFAULT_TIMEZONE", "America/New_York").strip(),
        database_url=os.getenv("DATABASE_URL", "sqlite:///lightbringer.db").strip(),
        google_client_id=_required("GOOGLE_CLIENT_ID"),
        google_client_secret=_required("GOOGLE_CLIENT_SECRET"),
        google_refresh_token=_required("GOOGLE_REFRESH_TOKEN"),
        racetime_categories=categories,
        twitch_client_id=_optional("TWITCH_CLIENT_ID", ""),
        twitch_client_secret=_optional("TWITCH_CLIENT_SECRET", ""),
    )
