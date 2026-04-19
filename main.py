import asyncio
import logging

import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_settings
from app.db import init_db, create_all
from app.services.calendar_service import CalendarService
from app.services.discord_event_service import DiscordEventService
from app.services.racetime_service import RacetimeService
from app.jobs.scheduler_jobs import SchedulerJobs
from app.commands.match_commands import MatchCommands

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lightbringer")

settings = get_settings()

init_db(settings.database_url)
create_all()

intents = discord.Intents.default()
bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    application_id=settings.application_id,
)
tree = bot.tree

calendar_service = CalendarService(settings)
racetime_service = RacetimeService(settings)
discord_event_service = DiscordEventService(bot, settings)

scheduler = AsyncIOScheduler()
scheduler_jobs = SchedulerJobs(
    bot,
    settings,
    calendar_service,
    racetime_service,
    discord_event_service,
)

_commands_synced = False


@bot.event
async def setup_hook():
    logger.info("setup_hook complete")


@bot.event
async def on_ready():
    global _commands_synced

    logger.info("Connected as %s (%s)", bot.user, bot.user.id if bot.user else "unknown")

    if not _commands_synced:
        guild = discord.Object(id=settings.guild_id)

        try:
            tree.clear_commands(guild=guild)
        except Exception as exc:
            logger.warning("Could not clear guild commands before sync: %s", exc)

        try:
            tree.add_command(
                MatchCommands(
                    settings,
                    calendar_service,
                    racetime_service,
                    discord_event_service,
                ),
                guild=guild,
                override=True,
            )
            synced = await tree.sync(guild=guild)
            logger.info("Synced %s command(s) to guild %s", len(synced), settings.guild_id)
            _commands_synced = True
        except Exception:
            logger.exception("Failed to sync application commands")

    if not scheduler.running:
        scheduler.add_job(
            scheduler_jobs.run,
            "interval",
            seconds=60,
            id="scheduler_jobs",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("Scheduler started")

    logger.info("Bot ready as %s", bot.user)


@bot.event
async def on_disconnect():
    logger.warning("Bot disconnected from Discord gateway")


@bot.event
async def on_resumed():
    logger.info("Bot session resumed")


async def main():
    async with bot:
        await bot.start(settings.discord_token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down bot")
        if scheduler.running:
            scheduler.shutdown(wait=False)