from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from sqlalchemy import select

from app.db import session_scope
from app.models import Match
from app.services.calendar_service import CalendarService
from app.services.discord_event_service import DiscordEventService
from app.services.match_service import MatchService
from app.services.olir_client import OLirClient
from app.services.racetime_result_service import RacetimeResultService
from app.services.racetime_service import RacetimeService
from app.services.reminder_service import ReminderService
from app.services.twitch_service import TwitchService
from app.utils.time_utils import discord_timestamp
from app.views.match_claim_view import MatchClaimView

logger = logging.getLogger("lightbringer")


class SchedulerJobs:
    def __init__(
        self,
        bot: discord.Client,
        settings,
        calendar_service: CalendarService,
        racetime_service: RacetimeService,
        discord_event_service: DiscordEventService,
    ):
        self.bot = bot
        self.settings = settings
        self.calendar_service = calendar_service
        self.racetime_service = racetime_service
        self.discord_event_service = discord_event_service
        self.reminders = ReminderService()
        self.match_service = MatchService()
        self.olir_client = OLirClient(settings)
        self.racetime_result_service = RacetimeResultService()
        self.twitch_service = TwitchService(settings)
        self.central_tz = ZoneInfo("America/Chicago")

    def _is_weekly(self, subcategory: str | None) -> bool:
        return "weekly" in str(subcategory or "").lower()

    def _is_tournament(self, subcategory: str | None) -> bool:
        return "tournament" in str(subcategory or "").lower()

    def _match_label(self, match: Match) -> str:
        title = match.stream_name or (
            match.team1 if self._is_weekly(match.subcategory) else f"{match.team1} vs {match.team2}"
        )
        return f"{match.id} ({title})"

    def _briefing_label(self, match: Match) -> str:
        return match.stream_name or f"{match.team1} vs {match.team2}"

    def _archive_thread_id(self, terminal_state: str) -> int:
        if terminal_state == "complete":
            return int(self.settings.completed_matches_thread_id)
        return int(self.settings.cancelled_matches_thread_id)

    def _assigned_archive_text(self, match: Match) -> str:
        if getattr(match, "assigned_display_name", None):
            return match.assigned_display_name
        if getattr(match, "assigned_discord_id", None):
            return str(match.assigned_discord_id)
        return "Unclaimed"

    def _local_start_text(self, match: Match) -> str:
        return discord_timestamp(match.start_at_utc, "t")

    def _player_mentions(self, match: Match) -> str:
        mentions: list[str] = []

        entrant1 = str(getattr(match, "entrant1_discord_id", "") or "").strip()
        entrant2 = str(getattr(match, "entrant2_discord_id", "") or "").strip()

        if entrant1:
            mentions.append(f"<@{entrant1}>")
        if entrant2 and entrant2 != entrant1:
            mentions.append(f"<@{entrant2}>")

        return " ".join(mentions)

    def _fallback_role_for_match(self, match: Match) -> int:
        if self._is_weekly(match.subcategory):
            weekly_roles = list(getattr(self.settings, "weekly_allowed_role_ids", []))
            if weekly_roles:
                return int(weekly_roles[0])
        return int(self.settings.fallback_role_id)

    def _reminder_channel_for_match(self, match: Match) -> int:
        if self._is_weekly(match.subcategory):
            return int(self.settings.weekly_reminder_channel_id)
        return int(self.settings.reminder_channel_id)

    def _weekly_ping_role_for_match(self, match: Match) -> int | None:
        role_map = getattr(self.settings, "weekly_ping_role_ids", {}) or {}
        if not self._is_weekly(match.subcategory):
            return None
        return role_map.get(str(match.category_slug).lower())

    def _created_before_checkpoint(self, match: Match, checkpoint_time: datetime) -> bool:
        created_at = getattr(match, "created_at_utc", None)
        if not created_at:
            return True
        return created_at <= checkpoint_time

    def _state_from_racetime_payload(self, data: dict) -> str | None:
        status_obj = data.get("status") or {}
        status_value = str(status_obj.get("value", "") or "").strip().lower()

        if status_value == "in_progress":
            return "active_race"
        if status_value == "finished":
            return "complete"
        if status_value == "cancelled":
            return "cancelled"
        return None

    def _assigned_display_text(self, match: Match) -> str:
        assigned_id = str(getattr(match, "assigned_discord_id", "") or "").strip()
        if assigned_id:
            return f"<@{assigned_id}>"
        return "Unassigned"

    def _briefing_claim_text(self, match: Match) -> str:
        assigned_id = str(getattr(match, "assigned_discord_id", "") or "").strip()
        if assigned_id:
            return f"**Claimed by <@{assigned_id}>**"
        return "**UNCLAIMED**"

    def _start_at_as_central(self, match: Match) -> datetime:
        dt = match.start_at_utc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(self.central_tz)

    async def _resolve_channel(self, channel_id: int | None):
        if not channel_id:
            return None

        channel = self.bot.get_channel(channel_id)
        if channel is not None:
            return channel

        try:
            return await self.bot.fetch_channel(channel_id)
        except Exception as exc:
            logger.warning("Could not resolve channel %s: %s", channel_id, exc)
            return None

    async def _safe_send(self, channel_id: int | None, message: str) -> discord.Message | None:
        channel = await self._resolve_channel(channel_id)
        if channel is None:
            logger.warning("Channel %s is unavailable for message: %s", channel_id, message)
            return None

        try:
            return await channel.send(message)
        except discord.Forbidden:
            logger.warning("Missing access to channel %s", channel_id)
            return None
        except discord.HTTPException as exc:
            logger.warning("Failed to send message to channel %s: %s", channel_id, exc)
            return None

    async def _log_notice(self, message: str) -> discord.Message | None:
        return await self._safe_send(int(self.settings.lightbringer_logs_thread_id), message)

    async def _send_result_to_olir(self, match: Match, race_data: dict) -> None:
        payload = self.racetime_result_service.build_olir_result_payload(match, race_data)
        if not payload:
            await self._log_notice(f"Could not build O-Lir result payload for `{self._match_label(match)}`.")
            return
        try:
            await self.olir_client.report_match_result(payload)
        except Exception as exc:
            logger.exception("Failed to report result to O-Lir for %s: %s", match.id, exc)
            await self._log_notice(f"Failed to report result to O-Lir for `{self._match_label(match)}`: {exc}")

    async def _delete_discord_message(self, channel_id: str | int, message_id: str | int) -> bool:
        try:
            channel = await self._resolve_channel(int(channel_id))
            if channel is None:
                return False
            message = await channel.fetch_message(int(message_id))
            await message.delete()
            return True
        except Exception as exc:
            logger.info("Could not delete message %s in channel %s: %s", message_id, channel_id, exc)
            return False

    async def _delete_tracked_message_types(self, session, match_id: str, message_types: list[str]) -> None:
        tracked = self.reminders.get_tracked_messages(session, match_id, message_types)
        for item in tracked:
            await self._delete_discord_message(item.channel_id, item.message_id)
        self.reminders.delete_tracked_messages(session, match_id, message_types)

    async def _delete_runtime_messages_for_terminal_state(self, session, match_id: str) -> None:
        keep_types = ["player_room_open", "weekly_room_open"]
        tracked = self.reminders.get_tracked_messages_excluding(session, match_id, keep_types)
        for item in tracked:
            await self._delete_discord_message(item.channel_id, item.message_id)
        self.reminders.delete_tracked_messages_excluding(session, match_id, keep_types)

    async def _refresh_claim_message(self, match: Match) -> None:
        channel_id = getattr(match, "claim_channel_id", None)
        message_id = getattr(match, "claim_message_id", None)
        if not channel_id or not message_id:
            return

        channel = await self._resolve_channel(int(channel_id))
        if channel is None or not isinstance(channel, discord.abc.Messageable):
            return

        try:
            message = await channel.fetch_message(int(message_id))
        except Exception:
            return

        role_pool = self.settings.weekly_allowed_role_ids if self._is_weekly(match.subcategory) else self.settings.allowed_role_ids
        primary_role_id = int(role_pool[0]) if role_pool else 0

        await message.edit(
            embed=MatchClaimView.build_embed(match),
            view=MatchClaimView(match.id, primary_role_id),
        )

    async def _safe_dm_user(self, user_id: str, message: str) -> bool:
        try:
            user = self.bot.get_user(int(user_id))
            if user is None:
                user = await self.bot.fetch_user(int(user_id))
            await user.send(message)
            return True
        except Exception as exc:
            logger.warning("Failed to DM user %s: %s", user_id, exc)
            return False

    async def _upsert_discord_event(self, match: Match) -> None:
        try:
            discord_event_id = await self.discord_event_service.upsert_event_for_match(match)
            if discord_event_id:
                self.match_service.mark_discord_event(match.id, discord_event_id)
                match.discord_event_id = discord_event_id
        except Exception as exc:
            logger.warning("Failed to upsert Discord scheduled event for %s: %s", match.id, exc)

    async def _delete_discord_event(self, match: Match) -> None:
        try:
            deleted = await self.discord_event_service.delete_event_for_match(match)
            if deleted:
                self.match_service.clear_discord_event(match.id)
        except Exception as exc:
            logger.warning("Failed to delete Discord scheduled event for %s: %s", match.id, exc)

    async def _archive_terminal_match(self, match: Match, terminal_state: str) -> None:
        thread = await self._resolve_channel(self._archive_thread_id(terminal_state))
        if thread is None or not isinstance(thread, discord.abc.Messageable):
            return

        lines = [
            f"{match.id} | {self._briefing_label(match)}",
            f"State: {terminal_state.title()}",
            f"Event: {match.category_slug} / {match.subcategory}",
            f"Claimed By: {self._assigned_archive_text(match)}",
            f"Start: {discord_timestamp(match.start_at_utc)}",
            f"Racetime: {match.racetime_room_url or 'Pending'}",
        ]
        if getattr(match, "speedgaming_url", None):
            lines.append(f"Restream: {match.speedgaming_url}")

        try:
            await thread.send("\n".join(lines))
        except Exception as exc:
            logger.warning("Failed to archive terminal match %s: %s", match.id, exc)

    async def _delete_claim_box_message(self, match: Match) -> None:
        channel_id = getattr(match, "claim_channel_id", None)
        message_id = getattr(match, "claim_message_id", None)

        if channel_id and message_id:
            try:
                await self._delete_discord_message(channel_id, message_id)
            except Exception:
                pass

        try:
            self.match_service.clear_claim_message(match.id)
        except Exception:
            pass

    async def _send_cgc_team_passwords(self, match: Match) -> None:
        if str(match.category_slug).lower() != "mpcgr" or self._is_weekly(match.subcategory):
            return

        team_payloads = [
            (
                "team1",
                [
                    str(getattr(match, "team1_player1_discord_id", "") or "").strip(),
                    str(getattr(match, "team1_player2_discord_id", "") or "").strip(),
                ],
                getattr(match, "team1_room_name", None),
                getattr(match, "team1_password", None),
                match.team1,
            ),
            (
                "team2",
                [
                    str(getattr(match, "team2_player1_discord_id", "") or "").strip(),
                    str(getattr(match, "team2_player2_discord_id", "") or "").strip(),
                ],
                getattr(match, "team2_room_name", None),
                getattr(match, "team2_password", None),
                match.team2,
            ),
        ]

        for team_key, player_ids, room_name, password, team_name in team_payloads:
            if not room_name or not password:
                logger.info("Incomplete room credentials for %s on %s, skipping DM", team_key, match.id)
                continue

            for user_id in [u for u in player_ids if u]:
                dm_text = (
                    f"Your RDV room for `{self._match_label(match)}` ({team_name}) is: `{room_name}`\n"
                    f"Password: `{password}`\n"
                    f"Match starts at {self._local_start_text(match)}.\n"
                    f"Racetime room: {match.racetime_room_url or 'Pending'}"
                )
                sent = await self._safe_dm_user(user_id, dm_text)
                if not sent:
                    await self._safe_send(
                        self.settings.admin_channel_id,
                        f"Failed to DM {team_key} player <@{user_id}> for `{self._match_label(match)}`."
                    )

    async def _handle_racetime_cancelled_match(self, session, match: Match) -> None:
        try:
            self.calendar_service.delete_match_event(match)
        except Exception as exc:
            logger.warning("Failed to delete calendar event for cancelled match %s: %s", match.id, exc)

        try:
            self.match_service.clear_calendar_event(match.id)
        except Exception as exc:
            logger.warning("Failed to clear calendar event reference for %s: %s", match.id, exc)

        await self._delete_discord_event(match)

        updated = self.match_service.cancel_match(match.id)
        if not updated:
            return

        await self._archive_terminal_match(updated, "cancelled")
        await self._delete_claim_box_message(updated)
        await self._delete_runtime_messages_for_terminal_state(session, match.id)

        notice_lines = [
            f"Racetime cancelled match `{match.id} ({self._match_label(match)})`.",
            f"Category: {match.category_slug}/{match.subcategory}",
            f"Scheduled start: {discord_timestamp(match.start_at_utc)}",
            f"Assigned organizer: {self._assigned_display_text(match)}",
        ]
        if match.racetime_room_url:
            notice_lines.append(f"Racetime room: {match.racetime_room_url}")
        notice_lines.append("Please update SpeedGaming / partner listings if applicable.")

        await self._safe_send(
            self._reminder_channel_for_match(match),
            "\n".join(notice_lines),
        )

        logger.info("Auto-cancelled %s from racetime state sync", match.id)

    async def _send_daily_tournament_briefing(self) -> None:
        now_central = datetime.now(self.central_tz)
        if now_central.hour < 10:
            return

        local_date = now_central.date()
        briefing_key = f"daily_briefing:{local_date.isoformat()}"
        reminder_type = "tournament_daily_list"

        with session_scope() as session:
            if self.reminders.already_sent(session, briefing_key, reminder_type):
                return

            stmt = select(Match).where(Match.status.not_in(["complete", "cancelled"]))
            matches = list(session.execute(stmt).scalars().all())

            todays_matches: list[Match] = []
            for match in matches:
                if not self._is_tournament(match.subcategory):
                    continue
                start_central = self._start_at_as_central(match)
                if start_central.date() == local_date:
                    todays_matches.append(match)

            if not todays_matches:
                self.reminders.mark_sent(session, briefing_key, reminder_type)
                return

            todays_matches.sort(key=lambda m: m.start_at_utc)

            heading_dt = datetime(
                year=local_date.year,
                month=local_date.month,
                day=local_date.day,
                hour=12,
                minute=0,
                second=0,
                tzinfo=self.central_tz,
            )
            heading_ts = int(heading_dt.timestamp())

            lines = [
                f"<@&{self.settings.fallback_role_id}>",
                f"Upcoming matches for <t:{heading_ts}:D>",
                "",
            ]

            for match in todays_matches:
                start_dt = match.start_at_utc
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=ZoneInfo("UTC"))
                start_ts = int(start_dt.timestamp())
                lines.append(
                    f"{self._briefing_label(match)} || <t:{start_ts}:t> || {self._briefing_claim_text(match)}"
                )

            sent_msg = await self._safe_send(self.settings.reminder_channel_id, "\n".join(lines))
            if sent_msg:
                self.reminders.track_message(session, briefing_key, reminder_type, sent_msg.channel.id, sent_msg.id)

            self.reminders.mark_sent(session, briefing_key, reminder_type)

    async def _scan_speedgaming_links(self) -> None:
        if not self.twitch_service.enabled():
            return

        now = datetime.utcnow()
        window_start = now + timedelta(minutes=4)
        window_end = now + timedelta(minutes=6)

        with session_scope() as session:
            stmt = select(Match).where(
                Match.status.not_in(["complete", "cancelled"]),
                Match.speedgaming_url.is_(None),
                Match.start_at_utc >= window_start,
                Match.start_at_utc <= window_end,
            )
            matches = list(session.execute(stmt).scalars().all())

        if not matches:
            return

        try:
            live_streams = await self.twitch_service.get_live_speedgaming_streams()
        except Exception as exc:
            logger.warning("Failed to scan Twitch SpeedGaming channels: %s", exc)
            await self._log_notice(f"Failed to scan Twitch SpeedGaming channels: {exc}")
            return

        for match in matches:
            if getattr(match, "speedgaming_url", None):
                continue

            best_stream = self.twitch_service.find_best_match(match, live_streams)
            if best_stream is None:
                continue

            try:
                updated = self.match_service.set_speedgaming_url(match.id, best_stream.url)
                if not updated:
                    continue

                self.calendar_service.upsert_match_event(updated)
                await self._upsert_discord_event(updated)
                await self._refresh_claim_message(updated)

                await self._log_notice(
                    f"Auto-linked SpeedGaming channel for `{self._match_label(updated)}`.\n"
                    f"Channel: {best_stream.url}\n"
                    f"Title: {best_stream.title}"
                )
            except Exception as exc:
                logger.warning("Failed to auto-link SpeedGaming URL for %s: %s", match.id, exc)
                await self._log_notice(
                    f"Failed to auto-link SpeedGaming URL for `{self._match_label(match)}`: {exc}"
                )

    async def run(self) -> None:
        logger.info("SchedulerJobs.run tick")
        await self.open_due_rooms()
        await self.send_due_seed_prompts()
        await self.send_time_reminders()
        await self.sync_racetime_room_states()
        await self._scan_speedgaming_links()
        await self._send_daily_tournament_briefing()

    async def open_due_rooms(self) -> None:
        now = datetime.utcnow()
        with session_scope() as session:
            stmt = select(Match).where(
                Match.status.not_in(["complete", "cancelled"]),
                Match.room_open_at_utc <= now,
                Match.racetime_room_url.is_(None),
                Match.status.in_(["assigned", "open", "ready", "seed_pending"]),
            )
            matches = list(session.execute(stmt).scalars().all())

            for match in matches:
                category = self.settings.racetime_categories[match.category_slug]
                if not category.enabled:
                    logger.info("Skipping disabled racetime category for match %s: %s", match.id, match.category_slug)
                    continue

                try:
                    data = await self.racetime_service.create_room_for_match(match)

                    room_url = data.get("room_url") or data.get("url")
                    if room_url:
                        room_url = self.racetime_service._normalize_room_url(room_url)
                    match.racetime_room_url = room_url

                    match.racetime_race_slug = data.get("slug")

                    websocket_bot_url = data.get("websocket_bot_url")
                    if not websocket_bot_url and room_url:
                        try:
                            room_data = await self.racetime_service.fetch_race(room_url)
                            websocket_bot_url = (
                                room_data.get("websocket_bot_url")
                                or room_data.get("websocket")
                                or room_data.get("bot", {}).get("websocket_bot_url")
                            )
                        except Exception as exc:
                            logger.exception(
                                "Failed to fetch race data for %s after room creation: %s",
                                match.id,
                                exc,
                            )

                    match.racetime_ws_url = websocket_bot_url
                    match.status = "room_opened"

                    self.calendar_service.upsert_match_event(match)
                    await self._upsert_discord_event(match)
                    await self._refresh_claim_message(match)

                    if self._is_weekly(match.subcategory):
                        ping_role_id = self._weekly_ping_role_for_match(match)
                        if ping_role_id:
                            weekly_message = (
                                f"<@&{ping_role_id}> weekly room is open for `{self._match_label(match)}`.\n"
                                f"Racetime room: {match.racetime_room_url}"
                            )
                            weekly_msg = await self._safe_send(self.settings.weekly_room_open_channel_id, weekly_message)
                            if weekly_msg:
                                self.reminders.track_message(session, match.id, "weekly_room_open", weekly_msg.channel.id, weekly_msg.id)
                    else:
                        player_alert_key = "player_alert_t30"
                        if not self.reminders.already_sent(session, match.id, player_alert_key):
                            mentions = self._player_mentions(match)
                            if mentions:
                                player_message = (
                                    f"{mentions} your match `{self._match_label(match)}` is live. "
                                    f"Match starts at {self._local_start_text(match)}. "
                                    f"Racetime room: {match.racetime_room_url}"
                                )
                            else:
                                player_message = (
                                    f"Match `{self._match_label(match)}` is live. "
                                    f"Match starts at {self._local_start_text(match)}. "
                                    f"Racetime room: {match.racetime_room_url}"
                                )

                            player_msg = await self._safe_send(self.settings.player_alert_channel_id, player_message)
                            if player_msg:
                                self.reminders.track_message(session, match.id, "player_room_open", player_msg.channel.id, player_msg.id)
                            self.reminders.mark_sent(session, match.id, player_alert_key)
                except Exception as exc:
                    logger.exception("Failed to open room for match %s", match.id)
                    await self._log_notice(
                        f"Failed to open room for `{self._match_label(match)}`: {exc}",
                    )

    async def send_due_seed_prompts(self) -> None:
        now = datetime.utcnow()
        with session_scope() as session:
            stmt = select(Match).where(
                Match.status.not_in(["complete", "cancelled"]),
                Match.seed_prompt_at_utc <= now,
                Match.status.in_(["assigned", "room_opened", "open", "ready", "seed_pending"]),
                Match.seed_status.in_(["pending", "submitted", "ready"]),
            )
            matches = list(session.execute(stmt).scalars().all())

            for match in matches:
                match_label = self._match_label(match)
                reminder_channel_id = self._reminder_channel_for_match(match)
                fallback_role_id = self._fallback_role_for_match(match)

                if match.seed_status == "pending":
                    reminder_key = "seed_prompt_due"

                    if self.reminders.already_sent(session, match.id, reminder_key):
                        continue

                    if match.assigned_discord_id:
                        message = f"<@{match.assigned_discord_id}> seed entry is due for `{match_label}` at T-20."
                    else:
                        message = f"<@&{fallback_role_id}> `{match_label}` is unassigned and needs seed entry at T-20."

                    sent_msg = await self._safe_send(reminder_channel_id, message)
                    if sent_msg:
                        self.reminders.track_message(session, match.id, "seed_prompt_due", sent_msg.channel.id, sent_msg.id)

                    match.status = "seed_pending"
                    self.reminders.mark_sent(session, match.id, reminder_key)
                    self.calendar_service.upsert_match_event(match)
                    await self._upsert_discord_event(match)
                    await self._refresh_claim_message(match)

                else:
                    room_update_key = "seed_room_info_ready"
                    cgc_password_dm_key = "cgc_password_dm_ready"

                    if not self.reminders.already_sent(session, match.id, room_update_key):
                        try:
                            await self.racetime_service.update_room_info_for_match(match, reveal_seed=True)
                            self.reminders.mark_sent(session, match.id, room_update_key)
                        except Exception as exc:
                            logger.exception("Failed to update racetime room info for %s: %s", match.id, exc)
                            await self._log_notice(f"Failed to update racetime room info for `{self._match_label(match)}`: {exc}")

                    if str(match.category_slug).lower() == "mpcgr" and not self._is_weekly(match.subcategory):
                        if not self.reminders.already_sent(session, match.id, cgc_password_dm_key):
                            try:
                                await self._send_cgc_team_passwords(match)
                                self.reminders.mark_sent(session, match.id, cgc_password_dm_key)
                            except Exception as exc:
                                logger.exception("Failed CGC password DMs for %s: %s", match.id, exc)
                                await self._log_notice(f"Failed CGC password DMs for `{self._match_label(match)}`: {exc}")

                    self.calendar_service.upsert_match_event(match)
                    await self._upsert_discord_event(match)
                    await self._refresh_claim_message(match)

    async def send_time_reminders(self) -> None:
        now = datetime.utcnow()

        with session_scope() as session:
            stmt = select(Match).where(Match.status.not_in(["complete", "cancelled"]))
            matches = list(session.execute(stmt).scalars().all())

            for match in matches:
                reminder_key = "t60start"
                if self.reminders.already_sent(session, match.id, reminder_key):
                    continue

                target = match.start_at_utc - timedelta(minutes=60)

                if not self._created_before_checkpoint(match, target):
                    self.reminders.mark_sent(session, match.id, reminder_key)
                    continue

                if now < target:
                    continue

                match_label = self._match_label(match)
                local_start = self._local_start_text(match)
                reminder_channel_id = self._reminder_channel_for_match(match)
                fallback_role_id = self._fallback_role_for_match(match)

                if match.assigned_discord_id:
                    message = (
                        f"<@{match.assigned_discord_id}> organizer reminder for `{match_label}`. "
                        f"Racetime setup opens in 30 minutes. Match starts at {local_start}."
                    )
                else:
                    message = (
                        f"<@&{fallback_role_id}> `{match_label}` is unclaimed. "
                        f"Racetime setup opens in 30 minutes. Match starts at {local_start}."
                    )

                sent_msg = await self._safe_send(reminder_channel_id, message)
                if sent_msg:
                    self.reminders.track_message(session, match.id, reminder_key, sent_msg.channel.id, sent_msg.id)

                self.reminders.mark_sent(session, match.id, reminder_key)

    async def sync_racetime_room_states(self) -> None:
        with session_scope() as session:
            stmt = select(Match).where(
                Match.status.not_in(["complete", "cancelled"]),
                Match.racetime_room_url.is_not(None),
            )
            matches = list(session.execute(stmt).scalars().all())

            for match in matches:
                try:
                    race_data = await self.racetime_service.fetch_race(match.racetime_room_url)
                    remote_state = self._state_from_racetime_payload(race_data)
                    if not remote_state:
                        continue

                    current_state = str(match.status or "").lower()

                    if remote_state == "active_race" and current_state not in {"active_race", "complete", "cancelled"}:
                        updated = self.match_service.mark_active_race(match.id)
                        if updated:
                            self.calendar_service.upsert_match_event(updated)
                            await self._upsert_discord_event(updated)
                            await self._refresh_claim_message(updated)
                            logger.info("Marked %s as active_race from racetime state sync", match.id)

                    elif remote_state == "complete" and current_state != "complete":
                        updated = self.match_service.mark_complete(match.id)
                        if updated:
                            self.calendar_service.upsert_match_event(updated)
                            await self._delete_discord_event(updated)
                            await self._archive_terminal_match(updated, "complete")
                            await self._delete_claim_box_message(updated)
                            await self._delete_runtime_messages_for_terminal_state(session, match.id)
                            await self._send_result_to_olir(updated, race_data)
                            logger.info("Auto-completed %s from racetime state sync", match.id)

                    elif remote_state == "cancelled" and current_state != "cancelled":
                        await self._handle_racetime_cancelled_match(session, match)

                except Exception as exc:
                    logger.exception("Failed to sync racetime state for %s: %s", match.id, exc)
                    await self._log_notice(f"Failed to sync racetime state for `{self._match_label(match)}`: {exc}")
