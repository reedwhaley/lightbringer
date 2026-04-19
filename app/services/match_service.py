from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from sqlalchemy import select

from app.db import session_scope
from app.models import Match


class MatchService:
    def _generate_match_id(self, category_slug: str) -> str:
        return f"{str(category_slug).upper()}-{secrets.token_hex(3).upper()}"

    def create_match(
        self,
        *,
        guild_id: str | int,
        created_by_discord_id: str | int,
        category_slug: str,
        subcategory: str,
        team1: str,
        team2: str,
        start_at_utc: datetime,
        stream_name: str | None = None,
        notes: str | None = None,
        entrant1_discord_id: str | None = None,
        entrant2_discord_id: str | None = None,
        team1_player1_discord_id: str | None = None,
        team1_player2_discord_id: str | None = None,
        team2_player1_discord_id: str | None = None,
        team2_player2_discord_id: str | None = None,
        team1_player1_name: str | None = None,
        team1_player2_name: str | None = None,
        team2_player1_name: str | None = None,
        team2_player2_name: str | None = None,
    ) -> Match:
        match_id = self._generate_match_id(category_slug)

        setup_at_utc = start_at_utc - timedelta(minutes=20)
        room_open_at_utc = start_at_utc - timedelta(minutes=30)
        seed_prompt_at_utc = start_at_utc - timedelta(minutes=20)

        match = Match(
            id=match_id,
            guild_id=str(guild_id),
            category_slug=category_slug,
            subcategory=subcategory,
            team1=team1,
            team2=team2,
            entrant1_discord_id=str(entrant1_discord_id) if entrant1_discord_id else None,
            entrant2_discord_id=str(entrant2_discord_id) if entrant2_discord_id else None,
            team1_player1_discord_id=str(team1_player1_discord_id) if team1_player1_discord_id else None,
            team1_player2_discord_id=str(team1_player2_discord_id) if team1_player2_discord_id else None,
            team2_player1_discord_id=str(team2_player1_discord_id) if team2_player1_discord_id else None,
            team2_player2_discord_id=str(team2_player2_discord_id) if team2_player2_discord_id else None,
            team1_player1_name=team1_player1_name,
            team1_player2_name=team1_player2_name,
            team2_player1_name=team2_player1_name,
            team2_player2_name=team2_player2_name,
            stream_name=stream_name,
            notes=notes,
            status="open",
            seed_status="pending",
            created_by_discord_id=str(created_by_discord_id),
            start_at_utc=start_at_utc,
            setup_at_utc=setup_at_utc,
            room_open_at_utc=room_open_at_utc,
            seed_prompt_at_utc=seed_prompt_at_utc,
        )

        with session_scope() as session:
            session.add(match)
            session.flush()
            session.refresh(match)
            return match

    def get_match(self, match_id: str) -> Match | None:
        with session_scope() as session:
            return session.get(Match, match_id)

    def list_matches(self, limit: int = 100) -> list[Match]:
        with session_scope() as session:
            stmt = (
                select(Match)
                .where(Match.status.not_in(["complete", "cancelled"]))
                .order_by(Match.start_at_utc.asc())
                .limit(limit)
            )
            return list(session.execute(stmt).scalars().all())

    def list_matches_for_user(self, user_id: str | int, limit: int = 25) -> list[Match]:
        user_id = str(user_id)
        with session_scope() as session:
            stmt = (
                select(Match)
                .where(
                    Match.status.not_in(["complete", "cancelled"]),
                    Match.assigned_discord_id == user_id,
                )
                .order_by(Match.start_at_utc.asc())
                .limit(limit)
            )
            return list(session.execute(stmt).scalars().all())

    def list_claimable_matches_for_user(self, user_id: str | int, limit: int = 50) -> list[Match]:
        with session_scope() as session:
            stmt = (
                select(Match)
                .where(
                    Match.status.not_in(["complete", "cancelled"]),
                    Match.assigned_discord_id.is_(None),
                )
                .order_by(Match.start_at_utc.asc())
                .limit(limit)
            )
            return list(session.execute(stmt).scalars().all())

    def list_cancellable_matches_for_user(
        self,
        user_id: str | int,
        *,
        include_all: bool = False,
        limit: int = 50,
    ) -> list[Match]:
        user_id = str(user_id)
        with session_scope() as session:
            stmt = select(Match).where(Match.status.not_in(["complete", "cancelled"]))

            matches = list(session.execute(stmt.order_by(Match.start_at_utc.asc()).limit(limit)).scalars().all())
            if include_all:
                return matches

            filtered: list[Match] = []
            for match in matches:
                participant_ids = {
                    str(getattr(match, "entrant1_discord_id", "") or ""),
                    str(getattr(match, "entrant2_discord_id", "") or ""),
                    str(getattr(match, "team1_player1_discord_id", "") or ""),
                    str(getattr(match, "team1_player2_discord_id", "") or ""),
                    str(getattr(match, "team2_player1_discord_id", "") or ""),
                    str(getattr(match, "team2_player2_discord_id", "") or ""),
                }
                if str(getattr(match, "assigned_discord_id", "") or "") == user_id or user_id in participant_ids:
                    filtered.append(match)
            return filtered[:limit]

    def assign_match(self, match_id: str, assigned_discord_id: str | int, assigned_display_name: str) -> Match | None:
        with session_scope() as session:
            match = session.get(Match, match_id)
            if not match:
                return None
            match.assigned_discord_id = str(assigned_discord_id)
            match.assigned_display_name = assigned_display_name
            if match.status in {"open", "ready"}:
                match.status = "assigned"
            session.flush()
            session.refresh(match)
            return match

    def unassign_match(self, match_id: str) -> Match | None:
        with session_scope() as session:
            match = session.get(Match, match_id)
            if not match:
                return None
            match.assigned_discord_id = None
            match.assigned_display_name = None
            if match.status == "assigned":
                match.status = "open"
            session.flush()
            session.refresh(match)
            return match

    def set_seed(self, match_id: str, seed_value: str) -> Match | None:
        with session_scope() as session:
            match = session.get(Match, match_id)
            if not match:
                return None
            match.seed_value = seed_value
            match.seed_status = "submitted"
            session.flush()
            session.refresh(match)
            return match

    def set_speedgaming_url(self, match_id: str, speedgaming_url: str) -> Match | None:
        with session_scope() as session:
            match = session.get(Match, match_id)
            if not match:
                return None
            cleaned = str(speedgaming_url or "").strip()
            match.speedgaming_url = cleaned or None
            session.flush()
            session.refresh(match)
            return match

    def set_team_room_credentials(self, match_id: str, team: str, room_name: str, password: str) -> Match | None:
        with session_scope() as session:
            match = session.get(Match, match_id)
            if not match:
                return None

            if team == "team1":
                match.team1_room_name = room_name
                match.team1_password = password
            elif team == "team2":
                match.team2_room_name = room_name
                match.team2_password = password
            else:
                return None

            session.flush()
            session.refresh(match)
            return match

    def mark_complete(self, match_id: str) -> Match | None:
        with session_scope() as session:
            match = session.get(Match, match_id)
            if not match:
                return None
            match.status = "complete"
            session.flush()
            session.refresh(match)
            return match

    def mark_active_race(self, match_id: str) -> Match | None:
        with session_scope() as session:
            match = session.get(Match, match_id)
            if not match:
                return None
            match.status = "active_race"
            session.flush()
            session.refresh(match)
            return match

    def cancel_match(self, match_id: str) -> Match | None:
        with session_scope() as session:
            match = session.get(Match, match_id)
            if not match:
                return None
            match.status = "cancelled"
            session.flush()
            session.refresh(match)
            return match

    def mark_calendar_event(self, match_id: str, event_id: str) -> Match | None:
        with session_scope() as session:
            match = session.get(Match, match_id)
            if not match:
                return None
            match.calendar_event_id = str(event_id)
            session.flush()
            session.refresh(match)
            return match

    def clear_calendar_event(self, match_id: str) -> Match | None:
        with session_scope() as session:
            match = session.get(Match, match_id)
            if not match:
                return None
            match.calendar_event_id = None
            session.flush()
            session.refresh(match)
            return match

    def mark_discord_event(self, match_id: str, event_id: str) -> Match | None:
        with session_scope() as session:
            match = session.get(Match, match_id)
            if not match:
                return None
            match.discord_event_id = str(event_id)
            session.flush()
            session.refresh(match)
            return match

    def clear_discord_event(self, match_id: str) -> Match | None:
        with session_scope() as session:
            match = session.get(Match, match_id)
            if not match:
                return None
            match.discord_event_id = None
            session.flush()
            session.refresh(match)
            return match

    def mark_claim_message(self, match_id: str, channel_id: str | int, message_id: str | int) -> Match | None:
        with session_scope() as session:
            match = session.get(Match, match_id)
            if not match:
                return None
            match.claim_channel_id = str(channel_id)
            match.claim_message_id = str(message_id)
            session.flush()
            session.refresh(match)
            return match

    def clear_claim_message(self, match_id: str) -> Match | None:
        with session_scope() as session:
            match = session.get(Match, match_id)
            if not match:
                return None
            match.claim_channel_id = None
            match.claim_message_id = None
            session.flush()
            session.refresh(match)
            return match