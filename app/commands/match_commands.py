from __future__ import annotations

import logging

import discord
from discord import app_commands

from app.config import Settings
from app.db import session_scope
from app.models import Match
from app.services.calendar_service import CalendarService
from app.services.discord_event_service import DiscordEventService
from app.services.match_service import MatchService
from app.services.racetime_service import RacetimeService
from app.services.reminder_service import ReminderService
from app.utils.time_utils import parse_local_time_to_utc, discord_timestamp
from app.views.match_claim_view import MatchClaimView

logger = logging.getLogger("lightbringer")

STANDARD_CATEGORIES = [
    app_commands.Choice(name="mpr", value="mpr"),
    app_commands.Choice(name="mp2r", value="mp2r"),
]

CGC_CATEGORY = [
    app_commands.Choice(name="mpcgr", value="mpcgr"),
]

TEAM_CHOICES = [
    app_commands.Choice(name="team1", value="team1"),
    app_commands.Choice(name="team2", value="team2"),
]

TIMEZONE_CHOICES = [
    "ET", "CT", "MT", "PT", "AKT", "HST", "UTC", "GMT", "BST", "CET", "CEST",
    "EET", "EEST", "IST", "JST", "KST", "SGT", "HKT", "AEST", "AEDT", "ACST",
    "ACDT", "AWST", "NZST", "NZDT",
]


class MatchCommands(app_commands.Group):
    def __init__(
        self,
        settings: Settings,
        calendar_service: CalendarService,
        racetime_service: RacetimeService,
        discord_event_service: DiscordEventService,
    ):
        super().__init__(name="match", description="Tournament match commands")
        self.settings = settings
        self.match_service = MatchService()
        self.calendar_service = calendar_service
        self.racetime_service = racetime_service
        self.discord_event_service = discord_event_service
        self.reminders = ReminderService()

    def _is_weekly(self, subcategory: str | None) -> bool:
        return "weekly" in str(subcategory or "").lower()

    def _is_tournament(self, subcategory: str | None) -> bool:
        return "tournament" in str(subcategory or "").lower()

    def _match_selector_label(self, match) -> str:
        title = match.stream_name or (
            match.team1 if self._is_weekly(match.subcategory) else f"{match.team1} vs {match.team2}"
        )
        return f"{match.id} ({title})"[:100]

    def _match_notice_label(self, match) -> str:
        return match.stream_name or (
            match.team1 if self._is_weekly(match.subcategory) else f"{match.team1} vs {match.team2}"
        )

    def _assigned_display(self, match) -> str:
        if getattr(match, "assigned_discord_id", None):
            return f"<@{match.assigned_discord_id}>"
        return "Unassigned"

    def _assigned_archive_text(self, match) -> str:
        if getattr(match, "assigned_display_name", None):
            return match.assigned_display_name
        if getattr(match, "assigned_discord_id", None):
            return str(match.assigned_discord_id)
        return "Unclaimed"

    def _claim_channel_id_for_subcategory(self, subcategory: str | None) -> int:
        if self._is_weekly(subcategory):
            return int(self.settings.weekly_reminder_channel_id)
        return int(self.settings.claim_channel_id)

    def _compose_seed_value(self, permalink: str, seed_hash: str) -> str:
        return f"{permalink.strip()} || {seed_hash.strip()}"

    def _archive_thread_id(self, terminal_state: str) -> int:
        if terminal_state == "complete":
            return int(self.settings.completed_matches_thread_id)
        return int(self.settings.cancelled_matches_thread_id)

    def _is_bot_admin_member(self, member: discord.Member) -> bool:
        admin_role_ids = {
            self.settings.tournament_admin_role_id,
            self.settings.server_admin_role_id,
        }
        user_role_ids = {role.id for role in member.roles}
        return bool(admin_role_ids.intersection(user_role_ids))

    async def _upsert_discord_event(self, match) -> None:
        try:
            discord_event_id = await self.discord_event_service.upsert_event_for_match(match)
            if discord_event_id:
                self.match_service.mark_discord_event(match.id, discord_event_id)
                match.discord_event_id = discord_event_id
        except Exception as exc:
            logger.warning("Failed to upsert Discord scheduled event for %s: %s", match.id, exc)

    async def _delete_discord_event(self, match) -> None:
        try:
            deleted = await self.discord_event_service.delete_event_for_match(match)
            if deleted:
                self.match_service.clear_discord_event(match.id)
        except Exception as exc:
            logger.warning("Failed to delete Discord scheduled event for %s: %s", match.id, exc)

    async def _resolve_member(self, interaction: discord.Interaction) -> discord.Member | None:
        guild = interaction.guild
        if guild is None:
            return None

        user = interaction.user
        if isinstance(user, discord.Member) and getattr(user, "roles", None):
            return user

        member = guild.get_member(user.id)
        if member is not None:
            return member

        try:
            return await guild.fetch_member(user.id)
        except Exception:
            return None

    async def _resolve_channel(self, interaction: discord.Interaction, channel_id: int | str | None):
        if not channel_id:
            return None

        guild = interaction.guild
        if guild is not None:
            channel = guild.get_channel(int(channel_id))
            if channel is not None:
                return channel

        try:
            return await interaction.client.fetch_channel(int(channel_id))
        except Exception:
            return None

    async def _archive_terminal_match(self, interaction: discord.Interaction, match, terminal_state: str) -> None:
        thread = await self._resolve_channel(interaction, self._archive_thread_id(terminal_state))
        if thread is None or not isinstance(thread, discord.abc.Messageable):
            return

        lines = [
            f"{match.id} | {self._match_notice_label(match)}",
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

    async def _delete_claim_box(self, interaction: discord.Interaction, match) -> None:
        channel_id = getattr(match, "claim_channel_id", None)
        message_id = getattr(match, "claim_message_id", None)

        if channel_id and message_id:
            channel = await self._resolve_channel(interaction, channel_id)
            if channel is not None:
                try:
                    message = await channel.fetch_message(int(message_id))
                    await message.delete()
                except Exception:
                    pass

        try:
            self.match_service.clear_claim_message(match.id)
        except Exception:
            pass

    async def _check_admin_only(self, interaction: discord.Interaction) -> tuple[bool, str]:
        guild = interaction.guild
        if guild is None:
            return False, "No guild context"

        try:
            if interaction.permissions and interaction.permissions.administrator:
                return True, "User has interaction administrator permission"
        except Exception:
            pass

        owner_id = getattr(guild, "owner_id", None)
        if owner_id is None:
            try:
                fetched_guild = await interaction.client.fetch_guild(guild.id)
                owner_id = fetched_guild.owner_id
            except Exception:
                owner_id = None

        if owner_id is not None and interaction.user.id == owner_id:
            return True, "User is guild owner"

        member = await self._resolve_member(interaction)
        if member is None:
            return False, "Could not resolve member"

        try:
            if member.guild_permissions.administrator:
                return True, "User has Discord Administrator permission"
        except Exception:
            pass

        if self._is_bot_admin_member(member):
            return True, "User has a bot admin role"

        return False, "User is not an admin"

    async def _check_access_for_subcategory(self, interaction: discord.Interaction, subcategory: str | None) -> tuple[bool, str]:
        is_admin, admin_reason = await self._check_admin_only(interaction)
        if is_admin:
            return True, admin_reason

        member = await self._resolve_member(interaction)
        if member is None:
            return False, "Could not resolve member"

        user_role_ids = {role.id for role in member.roles}

        if self._is_weekly(subcategory):
            allowed_role_ids = set(getattr(self.settings, "weekly_allowed_role_ids", []))
            if allowed_role_ids.intersection(user_role_ids):
                return True, "User has a weekly organizer role"
            return False, "Weekly organizer access required."

        allowed_role_ids = set(getattr(self.settings, "allowed_role_ids", []))
        if allowed_role_ids.intersection(user_role_ids):
            return True, "User has a tournament organizer role"
        return False, "Tournament organizer access required."

    async def _check_create_access_for_subcategory(self, interaction: discord.Interaction, subcategory: str | None) -> tuple[bool, str]:
        is_admin, admin_reason = await self._check_admin_only(interaction)
        if is_admin:
            return True, admin_reason

        member = await self._resolve_member(interaction)
        if member is None:
            return False, "Could not resolve member"

        user_role_ids = {role.id for role in member.roles}

        if self._is_weekly(subcategory):
            weekly_role_ids = set(getattr(self.settings, "weekly_allowed_role_ids", []))
            if weekly_role_ids.intersection(user_role_ids):
                return True, "User has a weekly organizer role"
            return False, "Weekly organizer access required."

        organizer_role_ids = set(getattr(self.settings, "allowed_role_ids", []))
        if organizer_role_ids.intersection(user_role_ids):
            return True, "User has a tournament organizer role"

        if self.settings.tournament_participant_role_id in user_role_ids:
            return True, "User has the tournament participant role"

        return False, "Tournament organizer or tournament participant access required."

    async def _can_access_match(self, interaction: discord.Interaction, match) -> bool:
        allowed, _ = await self._check_access_for_subcategory(interaction, getattr(match, "subcategory", ""))
        return allowed

    async def _refresh_claim_message(self, interaction: discord.Interaction, match) -> None:
        channel_id = getattr(match, "claim_channel_id", None)
        message_id = getattr(match, "claim_message_id", None)
        if not channel_id or not message_id:
            return

        channel = await self._resolve_channel(interaction, channel_id)
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

    async def _delete_runtime_messages(self, interaction: discord.Interaction, match_id: str) -> None:
        keep_types = {"player_room_open", "weekly_room_open"}

        async def _delete_discord_message(channel_id: str | int, message_id: str | int) -> bool:
            try:
                channel = await self._resolve_channel(interaction, channel_id)
                if channel is None:
                    return False
                message = await channel.fetch_message(int(message_id))
                await message.delete()
                return True
            except Exception:
                return False

        with session_scope() as session:
            tracked = self.reminders.get_tracked_messages_excluding(session, match_id, list(keep_types))
            for item in tracked:
                await _delete_discord_message(item.channel_id, item.message_id)
            self.reminders.delete_tracked_messages_excluding(session, match_id, list(keep_types))

    async def _safe_reminder_notice(self, interaction: discord.Interaction, message: str, weekly: bool) -> None:
        guild = interaction.guild
        if guild is None:
            return

        channel_id = self.settings.weekly_reminder_channel_id if weekly else self.settings.reminder_channel_id
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await interaction.client.fetch_channel(channel_id)
            except Exception:
                return

        if isinstance(channel, discord.abc.Messageable):
            try:
                await channel.send(message)
            except Exception:
                pass

    @app_commands.command(name="create", description="Create a standard 1v1 match")
    @app_commands.describe(
        category="Racetime category",
        subcategory="Racetime goal/subcategory, like tournament or weekly",
        team1="Entrant 1 name",
        team2="Entrant 2 name",
        team1_user="Optional Discord user for entrant 1",
        team2_user="Optional Discord user for entrant 2",
        start_local="Format: YYYY-MM-DD HH:MM or YYYY-MM-DD HHMM",
        timezone_name="Timezone like ET, BST, JST, or UTC",
        match_name="Required match title shown in events, lists, and claim cards",
        notes="Optional notes for match (RAs, etc) go here.",
    )
    @app_commands.choices(category=STANDARD_CATEGORIES)
    async def create(
        self,
        interaction: discord.Interaction,
        category: app_commands.Choice[str],
        subcategory: str,
        team1: str,
        team2: str,
        start_local: str,
        timezone_name: str,
        match_name: str,
        team1_user: discord.Member | None = None,
        team2_user: discord.Member | None = None,
        notes: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        allowed, reason = await self._check_create_access_for_subcategory(interaction, subcategory)
        if not allowed:
            await interaction.edit_original_response(content=reason)
            return

        try:
            start_at_utc = parse_local_time_to_utc(start_local, timezone_name)
        except Exception as exc:
            await interaction.edit_original_response(content=f"Could not parse time/timezone: {exc}")
            return

        match = self.match_service.create_match(
            guild_id=interaction.guild_id or self.settings.guild_id,
            created_by_discord_id=interaction.user.id,
            category_slug=category.value,
            subcategory=subcategory,
            team1=team1,
            team2=team2,
            entrant1_discord_id=str(team1_user.id) if team1_user else None,
            entrant2_discord_id=str(team2_user.id) if team2_user else None,
            start_at_utc=start_at_utc,
            stream_name=match_name,
            notes=notes,
        )

        event_id = self.calendar_service.upsert_match_event(match)
        if event_id:
            self.match_service.mark_calendar_event(match.id, event_id)

        await self._upsert_discord_event(match)

        claim_channel_id = self._claim_channel_id_for_subcategory(subcategory)
        claim_channel = interaction.guild.get_channel(claim_channel_id) if interaction.guild else None
        if claim_channel is None and interaction.guild:
            try:
                claim_channel = await interaction.client.fetch_channel(claim_channel_id)
            except Exception:
                claim_channel = None

        if claim_channel and isinstance(claim_channel, discord.abc.Messageable):
            role_pool = self.settings.weekly_allowed_role_ids if self._is_weekly(subcategory) else self.settings.allowed_role_ids
            primary_role_id = int(role_pool[0]) if role_pool else 0
            sent_message = await claim_channel.send(
                embed=MatchClaimView.build_embed(match),
                view=MatchClaimView(match.id, primary_role_id),
            )
            self.match_service.mark_claim_message(match.id, claim_channel.id, sent_message.id)

        await interaction.edit_original_response(
            content=f"Created match `{match.id}` for {discord_timestamp(match.start_at_utc)}."
        )

    @app_commands.command(name="create_cgc", description="Create a CGC team match")
    @app_commands.describe(
        category="Racetime category",
        subcategory="Racetime goal/subcategory",
        team1="Team 1 name",
        team2="Team 2 name",
        team1_player1_user="Team 1 Player 1",
        team1_player2_user="Team 1 Player 2",
        team2_player1_user="Team 2 Player 1",
        team2_player2_user="Team 2 Player 2",
        start_local="Format: YYYY-MM-DD HH:MM or YYYY-MM-DD HHMM",
        timezone_name="Timezone like ET, BST, JST, or UTC",
        match_name="Required match title shown in events, lists, and claim cards",
        notes="Optional notes for match (RAs, etc) go here.",
    )
    @app_commands.choices(category=CGC_CATEGORY)
    async def create_cgc(
        self,
        interaction: discord.Interaction,
        category: app_commands.Choice[str],
        subcategory: str,
        team1: str,
        team2: str,
        team1_player1_user: discord.Member,
        team1_player2_user: discord.Member,
        team2_player1_user: discord.Member,
        team2_player2_user: discord.Member,
        start_local: str,
        timezone_name: str,
        match_name: str,
        notes: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        allowed, reason = await self._check_create_access_for_subcategory(interaction, subcategory)
        if not allowed:
            await interaction.edit_original_response(content=reason)
            return

        try:
            start_at_utc = parse_local_time_to_utc(start_local, timezone_name)
        except Exception as exc:
            await interaction.edit_original_response(content=f"Could not parse time/timezone: {exc}")
            return

        match = self.match_service.create_match(
            guild_id=interaction.guild_id or self.settings.guild_id,
            created_by_discord_id=interaction.user.id,
            category_slug=category.value,
            subcategory=subcategory,
            team1=team1,
            team2=team2,
            team1_player1_discord_id=str(team1_player1_user.id),
            team1_player2_discord_id=str(team1_player2_user.id),
            team2_player1_discord_id=str(team2_player1_user.id),
            team2_player2_discord_id=str(team2_player2_user.id),
            team1_player1_name=team1_player1_user.display_name,
            team1_player2_name=team1_player2_user.display_name,
            team2_player1_name=team2_player1_user.display_name,
            team2_player2_name=team2_player2_user.display_name,
            start_at_utc=start_at_utc,
            stream_name=match_name,
            notes=notes,
        )

        event_id = self.calendar_service.upsert_match_event(match)
        if event_id:
            self.match_service.mark_calendar_event(match.id, event_id)

        await self._upsert_discord_event(match)

        claim_channel_id = self._claim_channel_id_for_subcategory(subcategory)
        claim_channel = interaction.guild.get_channel(claim_channel_id) if interaction.guild else None
        if claim_channel is None and interaction.guild:
            try:
                claim_channel = await interaction.client.fetch_channel(claim_channel_id)
            except Exception:
                claim_channel = None

        if claim_channel and isinstance(claim_channel, discord.abc.Messageable):
            role_pool = self.settings.weekly_allowed_role_ids if self._is_weekly(subcategory) else self.settings.allowed_role_ids
            primary_role_id = int(role_pool[0]) if role_pool else 0
            sent_message = await claim_channel.send(
                embed=MatchClaimView.build_embed(match),
                view=MatchClaimView(match.id, primary_role_id),
            )
            self.match_service.mark_claim_message(match.id, claim_channel.id, sent_message.id)

        await interaction.edit_original_response(
            content=f"Created CGC match `{match.id}` for {discord_timestamp(match.start_at_utc)}."
        )

    @create.autocomplete("subcategory")
    @create_cgc.autocomplete("subcategory")
    async def create_subcategory_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        raw_category = getattr(interaction.namespace, "category", None)
        category_slug: str | None = None

        if isinstance(raw_category, app_commands.Choice):
            category_slug = raw_category.value
        elif isinstance(raw_category, str):
            category_slug = raw_category.strip()

        if not category_slug:
            return []

        try:
            goals = await self.racetime_service.get_category_goals(category_slug)
        except Exception:
            return []

        current_lower = current.lower().strip()
        filtered = [goal for goal in goals if not current_lower or current_lower in goal.lower()]
        return [app_commands.Choice(name=goal, value=goal) for goal in filtered[:25]]

    @create.autocomplete("timezone_name")
    @create_cgc.autocomplete("timezone_name")
    async def create_timezone_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        current_lower = current.lower().strip()
        filtered = [tz for tz in TIMEZONE_CHOICES if not current_lower or current_lower in tz.lower()]
        return [app_commands.Choice(name=tz, value=tz) for tz in filtered[:25]]

    @app_commands.command(name="update", description="Update a scheduled match")
    @app_commands.describe(
        match_id="Match ID",
        match_name="Updated match title shown in events, lists, and claim cards",
        team1="Updated team or entrant 1 name",
        team2="Updated team or entrant 2 name",
        team1_user="Updated Discord user for entrant 1",
        team2_user="Updated Discord user for entrant 2",
        team1_player1_user="Updated CGC Team 1 Player 1",
        team1_player2_user="Updated CGC Team 1 Player 2",
        team2_player1_user="Updated CGC Team 2 Player 1",
        team2_player2_user="Updated CGC Team 2 Player 2",
        notes="Optional notes for match (RAs, etc) go here.",
    )
    async def update(
        self,
        interaction: discord.Interaction,
        match_id: str,
        match_name: str | None = None,
        team1: str | None = None,
        team2: str | None = None,
        team1_user: discord.Member | None = None,
        team2_user: discord.Member | None = None,
        team1_player1_user: discord.Member | None = None,
        team1_player2_user: discord.Member | None = None,
        team2_player1_user: discord.Member | None = None,
        team2_player2_user: discord.Member | None = None,
        notes: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        match = self.match_service.get_match(match_id)
        if not match:
            await interaction.edit_original_response(content="Match not found.")
            return

        is_admin, _ = await self._check_admin_only(interaction)
        is_assigned = str(match.assigned_discord_id) == str(interaction.user.id)

        if not (is_admin or is_assigned):
            await interaction.edit_original_response(
                content="Only the assigned organizer or an admin can update a match."
            )
            return

        change_count = 0

        with session_scope() as session:
            db_match = session.get(Match, match_id)
            if not db_match:
                await interaction.edit_original_response(content="Match not found.")
                return

            if match_name is not None and match_name.strip():
                db_match.stream_name = match_name.strip()
                change_count += 1

            if team1 is not None and team1.strip():
                db_match.team1 = team1.strip()
                change_count += 1

            if team2 is not None and team2.strip():
                db_match.team2 = team2.strip()
                change_count += 1

            if team1_user is not None:
                db_match.entrant1_discord_id = str(team1_user.id)
                change_count += 1

            if team2_user is not None:
                db_match.entrant2_discord_id = str(team2_user.id)
                change_count += 1

            if team1_player1_user is not None:
                db_match.team1_player1_discord_id = str(team1_player1_user.id)
                db_match.team1_player1_name = team1_player1_user.display_name
                change_count += 1

            if team1_player2_user is not None:
                db_match.team1_player2_discord_id = str(team1_player2_user.id)
                db_match.team1_player2_name = team1_player2_user.display_name
                change_count += 1

            if team2_player1_user is not None:
                db_match.team2_player1_discord_id = str(team2_player1_user.id)
                db_match.team2_player1_name = team2_player1_user.display_name
                change_count += 1

            if team2_player2_user is not None:
                db_match.team2_player2_discord_id = str(team2_player2_user.id)
                db_match.team2_player2_name = team2_player2_user.display_name
                change_count += 1

            if notes is not None:
                db_match.notes = notes.strip() if notes.strip() else None
                change_count += 1

            session.flush()
            session.refresh(db_match)

            updated = db_match

        if change_count == 0:
            await interaction.edit_original_response(content="No changes were provided.")
            return

        try:
            self.calendar_service.upsert_match_event(updated)
        except Exception:
            pass

        await self._upsert_discord_event(updated)

        try:
            await self._refresh_claim_message(interaction, updated)
        except Exception:
            pass

        await interaction.edit_original_response(
            content=f"Updated `{match_id}` successfully."
        )

    @update.autocomplete("match_id")
    async def update_match_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        is_admin, _ = await self._check_admin_only(interaction)
        if is_admin:
            matches = self.match_service.list_matches(limit=100)
        else:
            matches = self.match_service.list_matches_for_user(interaction.user.id, limit=50)

        current_lower = current.lower().strip()
        choices: list[app_commands.Choice[str]] = []
        for match in matches:
            label = self._match_selector_label(match)
            haystack = f"{match.id} {match.team1} {match.team2} {match.stream_name or ''}".lower()
            if not current_lower or current_lower in haystack:
                choices.append(app_commands.Choice(name=label, value=match.id))
            if len(choices) >= 25:
                break
        return choices[:25]

    @app_commands.command(name="assign", description="Assign a match to a user")
    async def assign(self, interaction: discord.Interaction, match_id: str, user: discord.Member) -> None:
        match = self.match_service.get_match(match_id)
        if not match:
            await interaction.response.send_message("Match not found.", ephemeral=True)
            return

        allowed, reason = await self._check_access_for_subcategory(interaction, match.subcategory)
        if not allowed:
            await interaction.response.send_message(reason, ephemeral=True)
            return

        updated = self.match_service.assign_match(match_id, user.id, user.display_name)
        if not updated:
            await interaction.response.send_message("Match not found.", ephemeral=True)
            return

        refreshed = self.match_service.get_match(match_id)
        if refreshed:
            self.calendar_service.upsert_match_event(refreshed)
            await self._upsert_discord_event(refreshed)
            await self._refresh_claim_message(interaction, refreshed)

        await interaction.response.send_message(f"Assigned `{match_id}` to {user.mention}.", ephemeral=True)

    @app_commands.command(name="claim", description="Claim an unassigned match")
    async def claim(self, interaction: discord.Interaction, match_id: str) -> None:
        match = self.match_service.get_match(match_id)
        if not match:
            await interaction.response.send_message("Match not found.", ephemeral=True)
            return

        allowed, reason = await self._check_access_for_subcategory(interaction, match.subcategory)
        if not allowed:
            await interaction.response.send_message(reason, ephemeral=True)
            return

        participant_ids = {
            str(getattr(match, "entrant1_discord_id", "") or ""),
            str(getattr(match, "entrant2_discord_id", "") or ""),
            str(getattr(match, "team1_player1_discord_id", "") or ""),
            str(getattr(match, "team1_player2_discord_id", "") or ""),
            str(getattr(match, "team2_player1_discord_id", "") or ""),
            str(getattr(match, "team2_player2_discord_id", "") or ""),
        }

        if str(interaction.user.id) in participant_ids:
            await interaction.response.send_message("You cannot claim a match you are participating in.", ephemeral=True)
            return

        if match.assigned_discord_id:
            await interaction.response.send_message(
                f"`{match_id}` is already claimed by {match.assigned_display_name or 'someone else'}.",
                ephemeral=True,
            )
            return

        updated = self.match_service.assign_match(match_id, interaction.user.id, interaction.user.display_name)
        if not updated:
            await interaction.response.send_message("Match not found.", ephemeral=True)
            return

        refreshed = self.match_service.get_match(match_id)
        if refreshed:
            self.calendar_service.upsert_match_event(refreshed)
            await self._upsert_discord_event(refreshed)
            await self._refresh_claim_message(interaction, refreshed)

        await interaction.response.send_message(f"You claimed `{match_id}`.", ephemeral=True)

    @claim.autocomplete("match_id")
    async def claim_match_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        all_matches = self.match_service.list_claimable_matches_for_user(interaction.user.id, limit=50)

        current_lower = current.lower().strip()
        choices: list[app_commands.Choice[str]] = []
        for match in all_matches:
            if not await self._can_access_match(interaction, match):
                continue
            label = self._match_selector_label(match)
            haystack = f"{match.id} {match.team1} {match.team2} {match.stream_name or ''}".lower()
            if not current_lower or current_lower in haystack:
                choices.append(app_commands.Choice(name=label, value=match.id))
            if len(choices) >= 25:
                break

        return choices[:25]

    @app_commands.command(name="set_seed", description="Set the seed permalink and hash for a match")
    @app_commands.describe(
        match_id="Match ID",
        permalink="Seed permalink/token",
        seed_hash="Seed hash text shown to runners",
    )
    async def set_seed(
        self,
        interaction: discord.Interaction,
        match_id: str,
        permalink: str,
        seed_hash: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        match = self.match_service.get_match(match_id)
        if not match:
            await interaction.edit_original_response(content="Match not found.")
            return

        is_admin, _ = await self._check_admin_only(interaction)
        is_assigned = str(match.assigned_discord_id) == str(interaction.user.id)

        if not (is_admin or is_assigned):
            await interaction.edit_original_response(
                content="Only the assigned organizer or an admin can set the seed."
            )
            return

        composed_seed = self._compose_seed_value(permalink, seed_hash)

        updated = self.match_service.set_seed(match_id, composed_seed)
        if not updated:
            await interaction.edit_original_response(content="Match not found.")
            return

        racetime_note = ""
        try:
            self.calendar_service.upsert_match_event(updated)
            await self._upsert_discord_event(updated)
        except Exception as exc:
            await interaction.edit_original_response(
                content=f"Seed saved in database for `{match_id}`, but calendar/event update failed: {exc}"
            )
            return

        try:
            await self._refresh_claim_message(interaction, updated)
        except Exception:
            pass

        if updated.racetime_room_url or updated.racetime_ws_url:
            try:
                await self.racetime_service.update_room_info_for_match(updated)
                racetime_note = " Calendar, Discord event, and Racetime updated."
            except Exception as exc:
                racetime_note = f" Calendar and Discord event updated, but Racetime update failed: {exc}"
        else:
            racetime_note = " Calendar and Discord event updated. Racetime room not open yet."

        await interaction.edit_original_response(
            content=f"Seed saved for `{match_id}`.{racetime_note}"
        )

    @set_seed.autocomplete("match_id")
    async def set_seed_match_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        matches = self.match_service.list_matches_for_user(interaction.user.id, limit=25)

        current_lower = current.lower().strip()
        choices: list[app_commands.Choice[str]] = []
        for match in matches:
            label = self._match_selector_label(match)
            haystack = f"{match.id} {match.team1} {match.team2} {match.stream_name or ''}".lower()
            if not current_lower or current_lower in haystack:
                choices.append(app_commands.Choice(name=label, value=match.id))

        return choices[:25]

    @app_commands.command(name="speedgaming", description="Set the SpeedGaming / restream Twitch URL for a match")
    @app_commands.describe(
        match_id="Match ID",
        url="SpeedGaming Twitch URL for the assigned restream",
    )
    async def speedgaming(self, interaction: discord.Interaction, match_id: str, url: str) -> None:
        await interaction.response.defer(ephemeral=True)

        match = self.match_service.get_match(match_id)
        if not match:
            await interaction.edit_original_response(content="Match not found.")
            return

        is_admin, _ = await self._check_admin_only(interaction)
        has_access, _ = await self._check_access_for_subcategory(interaction, match.subcategory)

        if not (is_admin or has_access):
            await interaction.edit_original_response(
                content="Only an organizer with access to this match type or an admin can set the SpeedGaming URL."
            )
            return

        updated = self.match_service.set_speedgaming_url(match_id, url)
        if not updated:
            await interaction.edit_original_response(content="Match not found.")
            return

        try:
            self.calendar_service.upsert_match_event(updated)
        except Exception:
            pass

        await self._upsert_discord_event(updated)

        try:
            await self._refresh_claim_message(interaction, updated)
        except Exception:
            pass

        await interaction.edit_original_response(
            content=f"SpeedGaming URL saved for `{match_id}` and Discord event updated."
        )

    @speedgaming.autocomplete("match_id")
    async def speedgaming_match_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        is_admin, _ = await self._check_admin_only(interaction)
        matches = self.match_service.list_matches(limit=100)

        current_lower = current.lower().strip()
        choices: list[app_commands.Choice[str]] = []
        for match in matches:
            allowed, _ = await self._check_access_for_subcategory(interaction, match.subcategory)
            if not (is_admin or allowed):
                continue
            label = self._match_selector_label(match)
            haystack = f"{match.id} {match.team1} {match.team2} {match.stream_name or ''}".lower()
            if not current_lower or current_lower in haystack:
                choices.append(app_commands.Choice(name=label, value=match.id))
            if len(choices) >= 25:
                break

        return choices[:25]

    @app_commands.command(name="password", description="Set RDV room name and password for a CGC team")
    @app_commands.describe(
        match_id="Match ID",
        team="Which team credentials to set",
        room_name="The RDV room name for that team",
        password="The RDV password for that team",
    )
    @app_commands.choices(team=TEAM_CHOICES)
    async def password(
        self,
        interaction: discord.Interaction,
        match_id: str,
        team: app_commands.Choice[str],
        room_name: str,
        password: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            match = self.match_service.get_match(match_id)
            if not match:
                await interaction.edit_original_response(content="Match not found.")
                return

            if str(match.category_slug).lower() != "mpcgr":
                await interaction.edit_original_response(content="`/match password` is currently only available for CGC matches.")
                return

            is_admin, _ = await self._check_admin_only(interaction)
            is_assigned = str(match.assigned_discord_id) == str(interaction.user.id)

            if not (is_admin or is_assigned):
                await interaction.edit_original_response(content="Only an admin or the assigned organizer can set team room credentials.")
                return

            updated = self.match_service.set_team_room_credentials(match_id, team.value, room_name, password)
            if not updated:
                await interaction.edit_original_response(content="Match not found.")
                return

            try:
                self.calendar_service.upsert_match_event(updated)
                await self._upsert_discord_event(updated)
                await self._refresh_claim_message(interaction, updated)
            except Exception:
                pass

            await interaction.edit_original_response(content=f"Saved room credentials for `{match_id}` {team.value}.")

        except Exception as exc:
            await interaction.edit_original_response(content=f"Failed to save room credentials for `{match_id}`: {exc}")

    @password.autocomplete("match_id")
    async def password_match_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        matches = self.match_service.list_matches_for_user(interaction.user.id, limit=25)

        current_lower = current.lower().strip()
        choices: list[app_commands.Choice[str]] = []
        for match in matches:
            if str(match.category_slug).lower() != "mpcgr":
                continue
            label = self._match_selector_label(match)
            haystack = f"{match.id} {match.team1} {match.team2} {match.stream_name or ''}".lower()
            if not current_lower or current_lower in haystack:
                choices.append(app_commands.Choice(name=label, value=match.id))

        return choices[:25]

    @app_commands.command(name="complete", description="Mark a match complete")
    async def complete(self, interaction: discord.Interaction, match_id: str) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            match = self.match_service.get_match(match_id)
            if not match:
                await interaction.edit_original_response(content="Match not found.")
                return

            is_admin, _ = await self._check_admin_only(interaction)
            is_assigned = str(match.assigned_discord_id) == str(interaction.user.id)

            if not (is_admin or is_assigned):
                await interaction.edit_original_response(content="Only the assigned organizer or an admin can complete a match.")
                return

            updated = self.match_service.mark_complete(match_id)
            if not updated:
                await interaction.edit_original_response(content="Match not found.")
                return

            try:
                self.calendar_service.upsert_match_event(updated)
            except Exception:
                pass

            await self._delete_discord_event(updated)
            await self._archive_terminal_match(interaction, updated, "complete")
            await self._delete_claim_box(interaction, updated)
            await self._delete_runtime_messages(interaction, match_id)

            await interaction.edit_original_response(content=f"Marked `{match_id}` complete.")

        except Exception as exc:
            await interaction.edit_original_response(content=f"Failed to complete `{match_id}`: {exc}")

    @complete.autocomplete("match_id")
    async def complete_match_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        matches = self.match_service.list_matches_for_user(interaction.user.id, limit=25)

        current_lower = current.lower().strip()
        choices: list[app_commands.Choice[str]] = []
        for match in matches:
            label = self._match_selector_label(match)
            haystack = f"{match.id} {match.team1} {match.team2} {match.stream_name or ''}".lower()
            if not current_lower or current_lower in haystack:
                choices.append(app_commands.Choice(name=label, value=match.id))

        return choices[:25]

    @app_commands.command(name="cancel", description="Cancel a match")
    async def cancel(self, interaction: discord.Interaction, match_id: str) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            match = self.match_service.get_match(match_id)
            if not match:
                await interaction.edit_original_response(content="Match not found.")
                return

            is_admin, _ = await self._check_admin_only(interaction)
            is_assigned = str(match.assigned_discord_id) == str(interaction.user.id)
            participant_ids = {
                str(getattr(match, "entrant1_discord_id", "") or ""),
                str(getattr(match, "entrant2_discord_id", "") or ""),
                str(getattr(match, "team1_player1_discord_id", "") or ""),
                str(getattr(match, "team1_player2_discord_id", "") or ""),
                str(getattr(match, "team2_player1_discord_id", "") or ""),
                str(getattr(match, "team2_player2_discord_id", "") or ""),
            }
            is_participant = str(interaction.user.id) in participant_ids

            if not (is_admin or is_assigned or is_participant):
                await interaction.edit_original_response(content="Only an admin, the assigned organizer, or a participant can cancel this match.")
                return

            try:
                self.calendar_service.delete_match_event(match)
            except Exception as exc:
                await interaction.edit_original_response(content=f"Failed to cancel `{match_id}`: calendar deletion error: {exc}")
                return

            self.match_service.clear_calendar_event(match_id)
            await self._delete_discord_event(match)

            updated = self.match_service.cancel_match(match_id)
            if not updated:
                await interaction.edit_original_response(content="Match not found.")
                return

            await self._archive_terminal_match(interaction, updated, "cancelled")
            await self._delete_claim_box(interaction, updated)
            await self._delete_runtime_messages(interaction, match_id)

            await interaction.edit_original_response(content=f"Cancelled `{match_id}`.")

            notice_lines = [
                f"Cancelled match `{match.id} ({self._match_notice_label(match)})`.",
                f"Category: {match.category_slug}/{match.subcategory}",
                f"Scheduled start: {discord_timestamp(match.start_at_utc)}",
                f"Assigned organizer: {self._assigned_display(match)}",
            ]
            if match.racetime_room_url:
                notice_lines.append(f"Racetime room: {match.racetime_room_url}")
            notice_lines.append("Please update SpeedGaming / partner listings if applicable.")

            await self._safe_reminder_notice(interaction, "\n".join(notice_lines), self._is_weekly(match.subcategory))

        except Exception as exc:
            await interaction.edit_original_response(content=f"Failed to cancel `{match_id}`: {exc}")

    @cancel.autocomplete("match_id")
    async def cancel_match_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        is_admin, _ = await self._check_admin_only(interaction)
        matches = self.match_service.list_cancellable_matches_for_user(
            interaction.user.id,
            include_all=is_admin,
            limit=50,
        )

        current_lower = current.lower().strip()
        choices: list[app_commands.Choice[str]] = []
        for match in matches:
            label = self._match_selector_label(match)
            haystack = f"{match.id} {match.team1} {match.team2} {match.stream_name or ''}".lower()
            if not current_lower or current_lower in haystack:
                choices.append(app_commands.Choice(name=label, value=match.id))
            if len(choices) >= 25:
                break

        return choices[:25]

    @app_commands.command(name="list", description="List upcoming matches")
    async def list(self, interaction: discord.Interaction) -> None:
        matches = self.match_service.list_matches()
        if not matches:
            await interaction.response.send_message("No matches scheduled.", ephemeral=True)
            return

        lines: list[str] = []
        for match in matches:
            weekly = self._is_weekly(match.subcategory)
            is_cgc = str(match.category_slug).lower() == "mpcgr"

            if weekly:
                lines.append(
                    f"`{match.id}` Match: {match.stream_name or match.team1} | "
                    f"{match.category_slug}/{match.subcategory} | "
                    f"{discord_timestamp(match.start_at_utc)} | "
                    f"{self._assigned_display(match)}"
                )
            elif is_cgc:
                team1_players = MatchClaimView._team_member_display(
                    match.team1_player1_discord_id,
                    match.team1_player2_discord_id,
                    match.team1_player1_name,
                    match.team1_player2_name,
                )
                team2_players = MatchClaimView._team_member_display(
                    match.team2_player1_discord_id,
                    match.team2_player2_discord_id,
                    match.team2_player1_name,
                    match.team2_player2_name,
                )
                lines.append(
                    f"`{match.id}` Team 1: {match.team1} [{team1_players}] | "
                    f"Team 2: {match.team2} [{team2_players}] | "
                    f"{match.category_slug}/{match.subcategory} | "
                    f"{discord_timestamp(match.start_at_utc)} | "
                    f"{self._assigned_display(match)}"
                )
            else:
                entrant1 = MatchClaimView._entrant_display(match.team1, getattr(match, "entrant1_discord_id", None))
                entrant2 = MatchClaimView._entrant_display(match.team2, getattr(match, "entrant2_discord_id", None))
                lines.append(
                    f"`{match.id}` Player 1: {entrant1} | "
                    f"Player 2: {entrant2} | "
                    f"{match.category_slug}/{match.subcategory} | "
                    f"{discord_timestamp(match.start_at_utc)} | "
                    f"{self._assigned_display(match)}"
                )

        await interaction.response.send_message("\n".join(lines[:15]), ephemeral=True)