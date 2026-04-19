from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from app.config import Settings
from app.models import Match
from app.utils.time_utils import utc_to_local_display


class CalendarService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._service = None

    def _credentials(self) -> Credentials:
        creds = Credentials(
            token=None,
            refresh_token=self.settings.google_refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.settings.google_client_id,
            client_secret=self.settings.google_client_secret,
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        creds.refresh(Request())
        return creds

    def _get_service(self):
        if self._service is None:
            self._service = build(
                "calendar",
                "v3",
                credentials=self._credentials(),
                cache_discovery=False,
            )
        return self._service

    def _is_weekly(self, subcategory: str | None) -> bool:
        return "weekly" in str(subcategory or "").lower()

    def _calendar_id_for(self, match: Match) -> str:
        category = self.settings.racetime_categories[match.category_slug]
        if self._is_weekly(match.subcategory):
            return category.weekly_calendar_id
        return category.calendar_id

    def _entrant_labels(self, category_slug: str) -> tuple[str, str]:
        if str(category_slug).lower() == "mpcgr":
            return "Team 1", "Team 2"
        return "Player 1", "Player 2"

    def _display_name(self, name: str, discord_id: str | None) -> str:
        if discord_id:
            return f"{name} (<@{discord_id}>)"
        return name

    def _assigned_display(self, match: Match) -> str:
        if match.assigned_discord_id:
            return f"<@{match.assigned_discord_id}>"
        return "Unassigned"

    def _summary(self, match: Match) -> str:
        if self._is_weekly(match.subcategory):
            return f"Setup: {match.stream_name or match.team1}"
        return f"Setup: {match.team1} vs {match.team2}"

    def _is_pre_t20(self, match: Match) -> bool:
        now_utc = datetime.now(timezone.utc)

        seed_prompt_at = match.seed_prompt_at_utc
        if seed_prompt_at.tzinfo is None:
            seed_prompt_at = seed_prompt_at.replace(tzinfo=timezone.utc)
        else:
            seed_prompt_at = seed_prompt_at.astimezone(timezone.utc)

        return now_utc < seed_prompt_at

    def _seed_display(self, match: Match) -> str:
        if self._is_pre_t20(match):
            return "[REDACTED]"
        return match.seed_value or "Pending"

    def _password_display(self, match: Match, password: str | None) -> str:
        if not password:
            return "Pending"
        if self._is_pre_t20(match):
            return "[REDACTED]"
        return password

    def _description(self, match: Match) -> str:
        weekly = self._is_weekly(match.subcategory)
        is_cgc = str(match.category_slug).lower() == "mpcgr"

        lines = [
            f"Match ID: {match.id}",
            f"Category: {match.category_slug}/{match.subcategory}",
        ]

        if weekly:
            lines.append(f"Match: {match.stream_name or match.team1}")
        elif is_cgc:
            lines.append(f"Team 1: {match.team1}")
            team1_names = ", ".join(
                [x for x in [match.team1_player1_name, match.team1_player2_name] if x]
            ) or "No players assigned"
            lines.append(f"Team 1 Players: {team1_names}")

            lines.append(f"Team 2: {match.team2}")
            team2_names = ", ".join(
                [x for x in [match.team2_player1_name, match.team2_player2_name] if x]
            ) or "No players assigned"
            lines.append(f"Team 2 Players: {team2_names}")

            lines.append(f"Team 1 Room: {match.team1_room_name or 'Pending'}")
            lines.append(f"Team 1 Password: {self._password_display(match, match.team1_password)}")
            lines.append(f"Team 2 Room: {match.team2_room_name or 'Pending'}")
            lines.append(f"Team 2 Password: {self._password_display(match, match.team2_password)}")
        else:
            label1, label2 = self._entrant_labels(match.category_slug)
            lines.append(
                f"{label1}: {self._display_name(match.team1, getattr(match, 'entrant1_discord_id', None))}"
            )
            lines.append(
                f"{label2}: {self._display_name(match.team2, getattr(match, 'entrant2_discord_id', None))}"
            )

        lines.extend(
            [
                f"Assigned Organizer: {self._assigned_display(match)}",
                f"Status: {match.status}",
                f"Seed Status: {match.seed_status}",
                f"Seed: {self._seed_display(match)}",
                f"Racetime Room: {match.racetime_room_url or 'Pending'}",
                f"Setup Start ({self.settings.default_timezone}): {utc_to_local_display(match.setup_at_utc, self.settings.default_timezone)}",
                f"Match Start ({self.settings.default_timezone}): {utc_to_local_display(match.start_at_utc, self.settings.default_timezone)}",
            ]
        )

        if match.stream_name and not weekly:
            lines.append(f"Match: {match.stream_name}")

        if match.notes:
            lines.append(f"Notes: {match.notes}")

        return "\n".join(lines)

    def upsert_match_event(self, match: Match) -> Optional[str]:
        body = {
            "summary": self._summary(match),
            "description": self._description(match),
            "start": {
                "dateTime": f"{match.setup_at_utc.isoformat()}Z",
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": f"{match.start_at_utc.isoformat()}Z",
                "timeZone": "UTC",
            },
            "extendedProperties": {
                "private": {
                    "match_id": match.id,
                    "category_slug": match.category_slug,
                    "subcategory": match.subcategory or "",
                    "assigned_discord_id": match.assigned_discord_id or "",
                    "entrant1_discord_id": getattr(match, "entrant1_discord_id", "") or "",
                    "entrant2_discord_id": getattr(match, "entrant2_discord_id", "") or "",
                    "racetime_room_url": match.racetime_room_url or "",
                    "seed_status": match.seed_status or "",
                }
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 60},
                    {"method": "popup", "minutes": 20},
                    {"method": "popup", "minutes": 5},
                ],
            },
        }

        service = self._get_service()
        calendar_id = self._calendar_id_for(match)

        if match.calendar_event_id:
            service.events().update(
                calendarId=calendar_id,
                eventId=match.calendar_event_id,
                body=body,
            ).execute()
            return match.calendar_event_id

        created = service.events().insert(
            calendarId=calendar_id,
            body=body,
        ).execute()
        return created.get("id")

    def delete_match_event(self, match: Match) -> bool:
        if not match.calendar_event_id:
            return False

        service = self._get_service()
        calendar_id = self._calendar_id_for(match)
        service.events().delete(
            calendarId=calendar_id,
            eventId=match.calendar_event_id,
        ).execute()
        return True