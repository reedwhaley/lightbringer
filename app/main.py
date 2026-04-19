from __future__ import annotations

import asyncio
import logging

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord import app_commands

from app.config import get_settings
from app.db import init_db, create_all
from app.services.calendar_service import CalendarService
from app.services.racetime_service import RacetimeService
from app.commands.match_commands import MatchCommands
from app.jobs.scheduler_jobs import SchedulerJobs

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lightbringer")

settings = get_settings()
init_db(settings.database_url)
create_all()

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
calendar_service = CalendarService(settings)
racetime_service = RacetimeService(settings)
scheduler = AsyncIOScheduler()


@client.event
async def on_ready() -> None:
    guild = discord.Object(id=settings.guild_id)
    tree.add_command(MatchCommands(settings, calendar_service, racetime_service), guild=guild)

    @tree.command(name="ping", description="Health check", guild=guild)
    async def ping(interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Pong. The bureaucracy lives.", ephemeral=True)

    await tree.sync(guild=guild)
    if not scheduler.running:
        jobs = SchedulerJobs(client, settings, calendar_service, racetime_service)
        scheduler.add_job(jobs.run, "interval", seconds=60, id="lightbringer-loop", replace_existing=True)
        scheduler.start()
    logger.info("Bot ready as %s", client.user)


if __name__ == "__main__":
    client.run(settings.discord_token)
