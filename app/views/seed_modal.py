from __future__ import annotations

import discord

from app.services.match_service import MatchService


class SeedModal(discord.ui.Modal, title="Enter Seed"):
    seed = discord.ui.TextInput(label="Seed URL or code", required=True, max_length=400)

    def __init__(self, match_id: str):
        super().__init__()
        self.match_id = match_id
        self.match_service = MatchService()

    async def on_submit(self, interaction: discord.Interaction) -> None:
        match = self.match_service.set_seed(self.match_id, str(self.seed))
        if not match:
            await interaction.response.send_message("Match not found.", ephemeral=True)
            return
        await interaction.response.send_message(f"Seed stored for `{self.match_id}`.", ephemeral=True)
