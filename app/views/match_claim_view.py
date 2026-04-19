from __future__ import annotations

import logging

import discord

from app.config import get_settings
from app.services.calendar_service import CalendarService
from app.services.discord_event_service import DiscordEventService
from app.services.match_service import MatchService
from app.utils.time_utils import discord_timestamp

logger = logging.getLogger("lightbringer")

_REASON_OPTIONS: list[tuple[str, str]] = [
    ("Assigned organizer no-show", "assigned_organizer_no_show"),
    ("Personal issue", "personal_issue"),
    ("Accidental claim", "accidental_claim"),
    ("Emergency coverage", "emergency_coverage"),
    ("Other", "other"),
]


def _settings():
    return get_settings()


def _is_weekly(subcategory: str | None) -> bool:
    return "weekly" in str(subcategory or "").lower()


def _is_tournament(subcategory: str | None) -> bool:
    return "tournament" in str(subcategory or "").lower()


def _human_status(status: str | None) -> str:
    value = str(status or "").replace("_", " ").strip()
    return value.title() if value else "Unknown"


def _assigned_display(match) -> str:
    if getattr(match, "assigned_discord_id", None):
        return f"<@{match.assigned_discord_id}>"
    return "Unclaimed"


def _participant_ids(match) -> set[str]:
    return {
        str(getattr(match, "entrant1_discord_id", "") or ""),
        str(getattr(match, "entrant2_discord_id", "") or ""),
        str(getattr(match, "team1_player1_discord_id", "") or ""),
        str(getattr(match, "team1_player2_discord_id", "") or ""),
        str(getattr(match, "team2_player1_discord_id", "") or ""),
        str(getattr(match, "team2_player2_discord_id", "") or ""),
    }


def _user_has_role(member: discord.Member, role_ids: list[int]) -> bool:
    user_role_ids = {role.id for role in member.roles}
    return bool(set(role_ids).intersection(user_role_ids))


def _is_bot_admin_member(member: discord.Member) -> bool:
    settings = _settings()
    admin_role_ids = {
        settings.tournament_admin_role_id,
        settings.server_admin_role_id,
    }
    user_role_ids = {role.id for role in member.roles}
    return bool(admin_role_ids.intersection(user_role_ids))


def _is_admin(interaction: discord.Interaction) -> bool:
    try:
        if interaction.permissions and interaction.permissions.administrator:
            return True
    except Exception:
        pass

    member = interaction.user
    if isinstance(member, discord.Member):
        try:
            if member.guild_permissions.administrator:
                return True
        except Exception:
            pass
        return _is_bot_admin_member(member)
    return False


def _can_access_match(interaction: discord.Interaction, match) -> bool:
    settings = _settings()
    member = interaction.user
    if _is_admin(interaction):
        return True
    if not isinstance(member, discord.Member):
        return False
    if _is_weekly(match.subcategory):
        return _user_has_role(member, settings.weekly_allowed_role_ids)
    return _user_has_role(member, settings.allowed_role_ids)


def _can_manage_tournament_claim(interaction: discord.Interaction, match) -> bool:
    settings = _settings()
    member = interaction.user
    if not _is_tournament(match.subcategory):
        return False
    if _is_admin(interaction):
        return True
    if not isinstance(member, discord.Member):
        return False
    return _user_has_role(member, settings.allowed_role_ids)


async def _resolve_channel(client: discord.Client, channel_id: int | str | None):
    if not channel_id:
        return None

    channel = client.get_channel(int(channel_id))
    if channel is not None:
        return channel

    try:
        return await client.fetch_channel(int(channel_id))
    except Exception as exc:
        logger.info("Could not resolve channel %s: %s", channel_id, exc)
        return None


async def _sync_match_records(client: discord.Client, match) -> None:
    settings = _settings()
    match_service = MatchService()

    try:
        calendar_service = CalendarService(settings)
        calendar_event_id = calendar_service.upsert_match_event(match)
        if calendar_event_id:
            match_service.mark_calendar_event(match.id, calendar_event_id)
            match.calendar_event_id = calendar_event_id
    except Exception as exc:
        logger.warning("Failed to sync calendar event for %s: %s", match.id, exc)

    try:
        discord_event_service = DiscordEventService(client, settings)
        discord_event_id = await discord_event_service.upsert_event_for_match(match)
        if discord_event_id:
            match_service.mark_discord_event(match.id, discord_event_id)
            match.discord_event_id = discord_event_id
    except Exception as exc:
        logger.warning("Failed to sync Discord event for %s: %s", match.id, exc)


async def _refresh_claim_message(client: discord.Client, match) -> None:
    channel_id = getattr(match, "claim_channel_id", None)
    message_id = getattr(match, "claim_message_id", None)
    if not channel_id or not message_id:
        return

    channel = await _resolve_channel(client, channel_id)
    if channel is None or not isinstance(channel, discord.abc.Messageable):
        return

    try:
        message = await channel.fetch_message(int(message_id))
    except Exception:
        return

    settings = _settings()
    role_pool = settings.weekly_allowed_role_ids if _is_weekly(match.subcategory) else settings.allowed_role_ids
    primary_role_id = int(role_pool[0]) if role_pool else 0

    await message.edit(
        embed=MatchClaimView.build_embed(match),
        view=MatchClaimView(match.id, primary_role_id),
    )


async def _log_admin_action(client: discord.Client, text: str) -> None:
    settings = _settings()
    channel = await _resolve_channel(client, settings.admin_channel_id)
    if channel is None or not isinstance(channel, discord.abc.Messageable):
        return
    try:
        await channel.send(text)
    except Exception as exc:
        logger.warning("Failed to log admin claim action: %s", exc)


class ManageReasonSelect(discord.ui.Select):
    def __init__(self, match_id: str, action_name: str, primary_role_id: int):
        self.match_id = match_id
        self.action_name = action_name
        self.primary_role_id = primary_role_id

        options = [
            discord.SelectOption(label=label, value=value)
            for label, value in _REASON_OPTIONS
        ]
        super().__init__(
            placeholder=f"Reason for {action_name.replace('_', ' ')}",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        match_service = MatchService()
        match = match_service.get_match(self.match_id)
        if not match:
            await interaction.response.edit_message(content="Match not found.", view=None)
            return

        if str(interaction.user.id) in _participant_ids(match):
            await interaction.response.edit_message(
                content="Participants cannot manage organizer claims for this match.",
                view=None,
            )
            return

        if not _can_manage_tournament_claim(interaction, match):
            await interaction.response.edit_message(
                content="Only tournament organizers or admins can manage claimed tournament matches.",
                view=None,
            )
            return

        reason_value = self.values[0]
        reason_label = next((label for label, value in _REASON_OPTIONS if value == reason_value), reason_value)

        old_assigned_id = str(getattr(match, "assigned_discord_id", "") or "").strip()
        old_assigned_display = _assigned_display(match)

        if not old_assigned_id:
            await interaction.response.edit_message(
                content="This match is no longer claimed.",
                view=None,
            )
            await _refresh_claim_message(interaction.client, match)
            return

        if self.action_name == "take_over":
            if old_assigned_id == str(interaction.user.id):
                await interaction.response.edit_message(
                    content="This match is already assigned to you.",
                    view=None,
                )
                return

            updated = match_service.assign_match(match.id, interaction.user.id, interaction.user.display_name)
            action_text = "taken over"
            new_assigned_text = f"<@{interaction.user.id}>"
        elif self.action_name == "unclaim":
            updated = match_service.unassign_match(match.id)
            action_text = "unclaimed"
            new_assigned_text = "Unclaimed"
        else:
            await interaction.response.edit_message(content="Unknown action.", view=None)
            return

        if not updated:
            await interaction.response.edit_message(content="Match not found.", view=None)
            return

        await _sync_match_records(interaction.client, updated)
        await _refresh_claim_message(interaction.client, updated)

        log_lines = [
            f"Claim management for `{updated.id} ({updated.stream_name or f'{updated.team1} vs {updated.team2}'})`",
            f"Action: {'Take over' if self.action_name == 'take_over' else 'Unclaim'}",
            f"Reason: {reason_label}",
            f"Previous organizer: {old_assigned_display}",
            f"New organizer: {new_assigned_text}",
            f"Changed by: <@{interaction.user.id}>",
        ]
        await _log_admin_action(interaction.client, "\n".join(log_lines))

        await interaction.response.edit_message(
            content=f"Match `{updated.id}` {action_text}. Reason: {reason_label}",
            view=None,
        )


class ManageReasonView(discord.ui.View):
    def __init__(self, match_id: str, action_name: str, primary_role_id: int):
        super().__init__(timeout=120)
        self.add_item(ManageReasonSelect(match_id, action_name, primary_role_id))


class ManageActionSelect(discord.ui.Select):
    def __init__(self, match_id: str, primary_role_id: int):
        self.match_id = match_id
        self.primary_role_id = primary_role_id
        options = [
            discord.SelectOption(label="Take over", value="take_over", description="Claim this match for yourself"),
            discord.SelectOption(label="Unclaim", value="unclaim", description="Return this match to the unclaimed pool"),
        ]
        super().__init__(
            placeholder="Choose a claim management action",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        match_service = MatchService()
        match = match_service.get_match(self.match_id)
        if not match:
            await interaction.response.edit_message(content="Match not found.", view=None)
            return

        if not _can_manage_tournament_claim(interaction, match):
            await interaction.response.edit_message(
                content="Only tournament organizers or admins can manage claimed tournament matches.",
                view=None,
            )
            return

        if str(interaction.user.id) in _participant_ids(match):
            await interaction.response.edit_message(
                content="Participants cannot manage organizer claims for this match.",
                view=None,
            )
            return

        action_name = self.values[0]
        await interaction.response.edit_message(
            content="Select a reason for this action:",
            view=ManageReasonView(self.match_id, action_name, self.primary_role_id),
        )


class ManageActionView(discord.ui.View):
    def __init__(self, match_id: str, primary_role_id: int):
        super().__init__(timeout=120)
        self.add_item(ManageActionSelect(match_id, primary_role_id))


class ClaimManageButton(discord.ui.Button):
    def __init__(self, match_id: str, primary_role_id: int):
        self.match_id = match_id
        self.primary_role_id = primary_role_id

        match = MatchService().get_match(match_id)
        status = str(getattr(match, "status", "") or "").lower()

        if status in {"complete", "cancelled", "active_race"}:
            label = "Unavailable"
            style = discord.ButtonStyle.secondary
            disabled = True
        else:
            assigned_id = str(getattr(match, "assigned_discord_id", "") or "").strip() if match else ""
            if assigned_id and match and _is_tournament(match.subcategory):
                label = "Unclaim / Takeover"
                style = discord.ButtonStyle.danger
                disabled = False
            elif assigned_id:
                label = "Claimed"
                style = discord.ButtonStyle.secondary
                disabled = False
            else:
                label = "Claim"
                style = discord.ButtonStyle.primary
                disabled = False

        super().__init__(
            label=label,
            style=style,
            custom_id="match_claim_manage_v2",
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        match_service = MatchService()
        match = match_service.get_match(self.match_id)
        if not match:
            await interaction.response.send_message("Match not found.", ephemeral=True)
            return

        if str(getattr(match, "status", "") or "").lower() in {"complete", "cancelled", "active_race"}:
            await interaction.response.send_message("This match can no longer be claimed or managed.", ephemeral=True)
            return

        if not _can_access_match(interaction, match):
            if _is_weekly(match.subcategory):
                await interaction.response.send_message("Weekly organizer access required.", ephemeral=True)
            else:
                await interaction.response.send_message("Tournament organizer access required.", ephemeral=True)
            return

        if str(interaction.user.id) in _participant_ids(match):
            await interaction.response.send_message(
                "Participants cannot claim or manage organizer ownership for this match.",
                ephemeral=True,
            )
            return

        assigned_id = str(getattr(match, "assigned_discord_id", "") or "").strip()

        if not assigned_id:
            updated = match_service.assign_match(match.id, interaction.user.id, interaction.user.display_name)
            if not updated:
                await interaction.response.send_message("Match not found.", ephemeral=True)
                return

            await _sync_match_records(interaction.client, updated)
            await _refresh_claim_message(interaction.client, updated)
            await interaction.response.send_message(f"You claimed `{updated.id}`.", ephemeral=True)
            return

        if not _is_tournament(match.subcategory):
            await interaction.response.send_message(
                f"This match is already claimed by {_assigned_display(match)}.",
                ephemeral=True,
            )
            return

        if not _can_manage_tournament_claim(interaction, match):
            await interaction.response.send_message(
                f"This match is already claimed by {_assigned_display(match)}.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"`{match.id}` is currently claimed by {_assigned_display(match)}. Choose an action:",
            ephemeral=True,
            view=ManageActionView(self.match_id, self.primary_role_id),
        )


class MatchClaimView(discord.ui.View):
    def __init__(self, match_id: str, primary_role_id: int):
        super().__init__(timeout=None)
        self.match_id = match_id
        self.primary_role_id = primary_role_id
        self.add_item(ClaimManageButton(match_id, primary_role_id))

    @staticmethod
    def _entrant_display(name: str, discord_id: str | None) -> str:
        if discord_id:
            return f"{name} (<@{discord_id}>)"
        return name

    @staticmethod
    def _team_member_display(
        discord_id_1: str | None,
        discord_id_2: str | None,
        name_1: str | None = None,
        name_2: str | None = None,
    ) -> str:
        values: list[str] = []
        if discord_id_1:
            values.append(f"<@{discord_id_1}>")
        elif name_1:
            values.append(name_1)

        if discord_id_2:
            values.append(f"<@{discord_id_2}>")
        elif name_2:
            values.append(name_2)

        return ", ".join(values) if values else "Unknown"

    @staticmethod
    def build_embed(match) -> discord.Embed:
        title = match.stream_name or (
            match.team1 if _is_weekly(match.subcategory) else f"{match.team1} vs {match.team2}"
        )
        embed = discord.Embed(title=title)

        embed.add_field(
            name="Event",
            value=f"{match.category_slug} / {match.subcategory}",
            inline=False,
        )

        if str(match.category_slug).lower() == "mpcgr":
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
            embed.add_field(name="Team 1", value=f"{match.team1} [{team1_players}]", inline=False)
            embed.add_field(name="Team 2", value=f"{match.team2} [{team2_players}]", inline=False)
        elif _is_weekly(match.subcategory):
            embed.add_field(name="Runners", value=match.stream_name or match.team1, inline=False)
        else:
            embed.add_field(
                name="Player 1",
                value=MatchClaimView._entrant_display(match.team1, getattr(match, "entrant1_discord_id", None)),
                inline=False,
            )
            embed.add_field(
                name="Player 2",
                value=MatchClaimView._entrant_display(match.team2, getattr(match, "entrant2_discord_id", None)),
                inline=False,
            )

        embed.add_field(name="Start", value=discord_timestamp(match.start_at_utc), inline=False)
        embed.add_field(name="Claimed By", value=_assigned_display(match), inline=True)
        embed.add_field(name="Match State", value=_human_status(match.status), inline=True)
        embed.add_field(name="Racetime", value=match.racetime_room_url or "Pending", inline=False)

        if getattr(match, "speedgaming_url", None):
            embed.add_field(name="Restream", value=match.speedgaming_url, inline=False)

        return embed