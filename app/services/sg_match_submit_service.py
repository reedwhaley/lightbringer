from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.services.sg_form_service import SGFormService, SGSubmitResult


@dataclass
class IdentitySnapshot:
    submitted_display_name: str
    discord_username_snapshot: str
    twitch_name: str


class SGMatchSubmitService:
    def __init__(self, settings: Settings) -> None:
        self.sg_form_service = SGFormService(settings)

    def _to_eastern_fields(self, scheduled_dt: datetime) -> tuple[str, str, str]:
        eastern = scheduled_dt.astimezone(ZoneInfo("America/New_York"))
        whendate = eastern.strftime("%m/%d/%Y")
        whentime = eastern.strftime("%I").lstrip("0") or "12"
        whenampm = eastern.strftime("%p").lower()
        return whendate, whentime, whenampm

    def submit_standard_match(
        self,
        *,
        category_slug: str,
        player1: IdentitySnapshot,
        player2: IdentitySnapshot,
        scheduled_dt: datetime,
        note: str = "",
        is_weekly: bool = False,
    ) -> SGSubmitResult:
        whendate, whentime, whenampm = self._to_eastern_fields(scheduled_dt)
        return self.sg_form_service.submit_standard_match(
            category_slug=category_slug,
            displayname1=player1.submitted_display_name,
            displayname2=player2.submitted_display_name,
            discordtag1=player1.discord_username_snapshot,
            discordtag2=player2.discord_username_snapshot,
            publicstream1=player1.twitch_name,
            publicstream2=player2.twitch_name,
            whendate=whendate,
            whentime=whentime,
            whenampm=whenampm,
            note=note,
            is_weekly=is_weekly,
        )

    def submit_cgc_match(
        self,
        *,
        category_slug: str,
        team1_player1: IdentitySnapshot,
        team1_player2: IdentitySnapshot,
        team2_player1: IdentitySnapshot,
        team2_player2: IdentitySnapshot,
        scheduled_dt: datetime,
        note: str = "",
        is_weekly: bool = False,
    ) -> SGSubmitResult:
        whendate, whentime, whenampm = self._to_eastern_fields(scheduled_dt)
        return self.sg_form_service.submit_cgc_match(
            category_slug=category_slug,
            displayname1=team1_player1.submitted_display_name,
            displayname2=team1_player2.submitted_display_name,
            displayname3=team2_player1.submitted_display_name,
            displayname4=team2_player2.submitted_display_name,
            discordtag1=team1_player1.discord_username_snapshot,
            discordtag2=team1_player2.discord_username_snapshot,
            discordtag3=team2_player1.discord_username_snapshot,
            discordtag4=team2_player2.discord_username_snapshot,
            publicstream1=team1_player1.twitch_name,
            publicstream2=team1_player2.twitch_name,
            publicstream3=team2_player1.twitch_name,
            publicstream4=team2_player2.twitch_name,
            whendate=whendate,
            whentime=whentime,
            whenampm=whenampm,
            note=note,
            is_weekly=is_weekly,
        )