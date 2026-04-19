from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import discord

from app.models import Match

logger = logging.getLogger("lightbringer")


class DiscordEventService:
    def __init__(self, bot: discord.Client, settings):
        self.bot = bot
        self.settings = settings

    async def _resolve_guild(self) -> discord.Guild | None:
        guild_id = int(self.settings.guild_id)
        guild = self.bot.get_guild(guild_id)
        if guild is not None:
            return guild

        try:
            return await self.bot.fetch_guild(guild_id)
        except Exception as exc:
            logger.warning("Could not resolve guild %s for scheduled events: %s", guild_id, exc)
            return None

    async def _fetch_event(self, guild: discord.Guild, event_id: str | int):
        try:
            cached = guild.get_scheduled_event(int(event_id))
            if cached is not None:
                return cached
        except Exception:
            pass

        try:
            return await guild.fetch_scheduled_event(int(event_id))
        except Exception as exc:
            logger.info("Could not fetch scheduled event %s: %s", event_id, exc)
            return None

    def _base_title(self, match: Match) -> str:
        return match.stream_name or f"{match.team1} vs {match.team2}"

    def _event_title(self, match: Match) -> str:
        base = self._base_title(match).strip()
        subcategory = str(match.subcategory or "").strip()
        if subcategory:
            return f"{base} | {subcategory}"[:100]
        return base[:100]

    def _runners_text(self, match: Match) -> str:
        return match.stream_name or f"{match.team1} vs {match.team2}"

    def _start_dt(self, match: Match) -> datetime:
        dt = match.start_at_utc
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _end_dt(self, start_dt: datetime) -> datetime:
        return start_dt + timedelta(hours=2)

    def _description(self, match: Match) -> str:
        start_dt = self._start_dt(match)
        unix_ts = int(start_dt.timestamp())
        return (
            f"Runners: {self._runners_text(match)}\n"
            f"Start Time: <t:{unix_ts}:f>\n"
            f"Racetime: {match.racetime_room_url or 'Pending'}\n"
            f"Restream: {match.speedgaming_url or 'Pending'}"
        )

    async def upsert_event_for_match(self, match: Match) -> str | None:
        guild = await self._resolve_guild()
        if guild is None:
            return None

        start_dt = self._start_dt(match)
        end_dt = self._end_dt(start_dt)

        event_kwargs = {
            "name": self._event_title(match),
            "description": self._description(match),
            "start_time": start_dt,
            "end_time": end_dt,
            "entity_type": discord.EntityType.external,
            "privacy_level": discord.PrivacyLevel.guild_only,
            "location": match.speedgaming_url or match.racetime_room_url or "Racetime.gg",
            "reason": f"Sync match {match.id}",
        }

        existing_id = str(getattr(match, "discord_event_id", "") or "").strip()
        if existing_id:
            existing = await self._fetch_event(guild, existing_id)
            if existing is not None:
                await existing.edit(**event_kwargs)
                logger.info("Updated Discord scheduled event %s for match %s", existing.id, match.id)
                return str(existing.id)

        created = await guild.create_scheduled_event(**event_kwargs)
        logger.info("Created Discord scheduled event %s for match %s", created.id, match.id)
        return str(created.id)

    async def delete_event_for_match(self, match: Match) -> bool:
        guild = await self._resolve_guild()
        if guild is None:
            return False

        existing_id = str(getattr(match, "discord_event_id", "") or "").strip()
        if not existing_id:
            return False

        existing = await self._fetch_event(guild, existing_id)
        if existing is None:
            return False

        try:
            await existing.delete()
            logger.info("Deleted Discord scheduled event %s for match %s", existing.id, match.id)
            return True
        except Exception as exc:
            logger.warning("Failed to delete Discord scheduled event %s for match %s: %s", existing_id, match.id, exc)
            return False