from __future__ import annotations

import logging

import discord
from discord.ui import Button, Modal, TextInput, View

from app.config import get_settings
from app.services.match_service import MatchService
from app.services.sg_form_service import SGFormService

logger = logging.getLogger("lightbringer")


class CrewSignupModal(Modal):
    def __init__(self, match_id: str, role_type: str, parent_view: "CrewSignupView") -> None:
        super().__init__(title=f"{role_type.title()} Signup")
        self.match_id = match_id
        self.role_type = role_type
        self.parent_view = parent_view

        self.display_name_input = TextInput(
            label="Display Name",
            placeholder="How should your name appear on the restream?",
            required=True,
            max_length=200,
        )
        self.twitch_name_input = TextInput(
            label="Twitch Name",
            placeholder="Your Twitch username.",
            required=True,
            max_length=100,
        )

        self.add_item(self.display_name_input)
        self.add_item(self.twitch_name_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        service = MatchService()
        match = service.get_match(self.match_id)
        if match is None:
            await interaction.response.send_message("Match not found.", ephemeral=True)
            return

        display_name = str(self.display_name_input.value).strip()
        twitch_name = str(self.twitch_name_input.value).strip()
        discord_username = str(interaction.user.name)

        existing = service.list_crew_signups(self.match_id, self.role_type)
        if any(str(row.discord_id) == str(interaction.user.id) for row in existing):
            await interaction.response.send_message(
                f"You already signed up for {self.role_type} on this match.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        sg_episode_id = str(getattr(match, "sg_episode_id", "") or "").strip()
        if not sg_episode_id:
            await interaction.followup.send(
                "Match has not been approved on SpeedGaming. Please try again later.",
                ephemeral=True,
            )
            return

        try:
            sg_form_service = SGFormService(get_settings())

            if self.role_type == "comms":
                sg_result = sg_form_service.submit_commentator_signup(
                    episode_id=sg_episode_id,
                    displayname=display_name,
                    discordtag=discord_username,
                    publicstream=twitch_name,
                )
            elif self.role_type == "tracker":
                sg_result = sg_form_service.submit_tracker_signup(
                    episode_id=sg_episode_id,
                    displayname=display_name,
                    discordtag=discord_username,
                    publicstream=twitch_name,
                )
            else:
                await interaction.followup.send(
                    f"Unknown signup role: {self.role_type}",
                    ephemeral=True,
                )
                return

        except Exception as exc:
            logger.warning(
                "Failed SG %s signup for %s on %s: %s",
                self.role_type,
                interaction.user.id,
                self.match_id,
                exc,
            )
            await interaction.followup.send(
                f"SG signup failed: {exc}",
                ephemeral=True,
            )
            return

        if not sg_result.ok:
            await interaction.followup.send(
                sg_result.message,
                ephemeral=True,
            )
            return

        try:
            service.add_crew_signup(
                match_id=self.match_id,
                role_type=self.role_type,
                discord_id=str(interaction.user.id),
                discord_username=discord_username,
                display_name=display_name,
                twitch_name=twitch_name,
            )
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        await self.parent_view.refresh_message(interaction)
        await interaction.followup.send(
            f"Signed up for {self.role_type}.\n{sg_result.message}",
            ephemeral=True,
        )


class CrewSignupView(View):
    def __init__(self, match_id: str, timeout: float | None = None) -> None:
        super().__init__(timeout=timeout)
        self.match_id = match_id
        self.service = MatchService()

    @staticmethod
    def _signup_lines(signups) -> str:
        if not signups:
            return "No signups yet."
        return "\n".join(
            f"{row.display_name} | Twitch: {row.twitch_name} | Discord: {row.discord_username}"
            for row in signups
        )

    @staticmethod
    def _sg_commentator_signup_url(match) -> str | None:
        episode_id = str(getattr(match, "sg_episode_id", "") or "").strip()
        if not episode_id:
            return None
        return f"https://speedgaming.org/commentator/signup/{episode_id}/"

    @staticmethod
    def _sg_tracker_signup_url(match) -> str | None:
        episode_id = str(getattr(match, "sg_episode_id", "") or "").strip()
        if not episode_id:
            return None
        return f"https://speedgaming.org/tracker/signup/{episode_id}/"

    @classmethod
    def build_embed(cls, match, comms_signups: list, tracker_signups: list) -> discord.Embed:
        title = match.stream_name or f"{match.team1} vs {match.team2}"
        embed = discord.Embed(title=f"Crew Signups | {title}")
        embed.add_field(name="Match ID", value=match.id, inline=False)
        embed.add_field(name="Category", value=f"{match.category_slug} / {match.subcategory}", inline=False)

        comms_url = cls._sg_commentator_signup_url(match)
        if comms_url:
            embed.add_field(name="SpeedGaming Comms Signup", value=comms_url, inline=False)

        tracker_url = cls._sg_tracker_signup_url(match)
        if tracker_url:
            embed.add_field(name="SpeedGaming Tracker Signup", value=tracker_url, inline=False)

        embed.add_field(name="Comms Signups", value=cls._signup_lines(comms_signups), inline=False)
        embed.add_field(name="Tracker Signups", value=cls._signup_lines(tracker_signups), inline=False)
        return embed

    async def refresh_message(self, interaction: discord.Interaction) -> None:
        match = self.service.get_match(self.match_id)
        if match is None:
            return

        comms = self.service.list_crew_signups(self.match_id, "comms")
        trackers = self.service.list_crew_signups(self.match_id, "tracker")
        embed = self.build_embed(match, comms, trackers)

        message = interaction.message
        if message is not None:
            await message.edit(embed=embed, view=self)

    @discord.ui.button(label="Comms Signup", style=discord.ButtonStyle.primary, custom_id="crew_signup_comms")
    async def comms_button(self, interaction: discord.Interaction, button: Button) -> None:
        await interaction.response.send_modal(CrewSignupModal(self.match_id, "comms", self))

    @discord.ui.button(label="Tracker Signup", style=discord.ButtonStyle.secondary, custom_id="crew_signup_tracker")
    async def tracker_button(self, interaction: discord.Interaction, button: Button) -> None:
        await interaction.response.send_modal(CrewSignupModal(self.match_id, "tracker", self))