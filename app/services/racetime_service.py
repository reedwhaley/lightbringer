from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import websockets

from app.config import Settings
from app.models import Match

logger = logging.getLogger("lightbringer")


class RacetimeService:
    TOKEN_URL = "https://racetime.gg/o/token"
    HTTP_BASE = "https://racetime.gg"
    WS_BASE = "wss://racetime.gg"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._token_cache: dict[str, str] = {}
        self._goals_cache: dict[str, tuple[datetime, list[str]]] = {}

    async def get_access_token(self, category_slug: str) -> str:
        if category_slug in self._token_cache:
            return self._token_cache[category_slug]

        category = self.settings.racetime_categories[category_slug]
        if not category.enabled:
            raise RuntimeError(f"Racetime category '{category_slug}' is not enabled")

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": category.client_id,
                    "client_secret": category.client_secret,
                },
            )
            response.raise_for_status()
            token = response.json()["access_token"]
            self._token_cache[category_slug] = token
            return token

    async def get_category_goals(self, category_slug: str, force_refresh: bool = False) -> list[str]:
        now = datetime.now(timezone.utc)
        cached = self._goals_cache.get(category_slug)
        if cached and not force_refresh:
            expires_at, goals = cached
            if expires_at > now:
                return goals

        url = f"{self.HTTP_BASE}/{category_slug}/data"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        goals = [str(goal).strip() for goal in data.get("goals", []) if str(goal).strip()]
        self._goals_cache[category_slug] = (now + timedelta(minutes=10), goals)
        return goals

    def _full_room_url(self, room_url: str) -> str:
        if not room_url:
            return room_url
        if room_url.startswith("http://") or room_url.startswith("https://"):
            return room_url
        if room_url.startswith("/"):
            return f"{self.HTTP_BASE}{room_url}"
        return f"{self.HTTP_BASE}/{room_url}"

    def _full_websocket_url(self, websocket_url: str, token: str) -> str:
        if websocket_url.startswith("ws://") or websocket_url.startswith("wss://"):
            base = websocket_url
        elif websocket_url.startswith("/"):
            base = f"{self.WS_BASE}{websocket_url}"
        else:
            base = f"{self.WS_BASE}/{websocket_url}"

        separator = "&" if "?" in base else "?"
        return f"{base}{separator}{urlencode({'token': token})}"

    # Compatibility aliases for callers that still use the newer helper names.
    def _normalize_room_url(self, room_url: str) -> str:
        return self._full_room_url(room_url)

    def _normalize_websocket_url(self, websocket_url: str) -> str:
        if not websocket_url:
            return websocket_url
        if websocket_url.startswith("ws://") or websocket_url.startswith("wss://"):
            return websocket_url
        if websocket_url.startswith("/"):
            return f"{self.WS_BASE}{websocket_url}"
        return f"{self.WS_BASE}/{websocket_url}"

    def _is_weekly(self, subcategory: str | None) -> bool:
        return "weekly" in str(subcategory or "").lower()

    def _is_ranked_goal(self, goal: str | None) -> bool:
        goal_text = str(goal or "").lower()
        return "tournament" in goal_text or "weekly" in goal_text

    def build_match_label(self, match: Match) -> str:
        return match.stream_name or (
            match.team1 if self._is_weekly(match.subcategory) else f"{match.team1} vs {match.team2}"
        )

    def build_room_open_user_text(self, match: Match) -> str:
        return f"Match: {self.build_match_label(match)}"

    def build_room_open_bot_text(self, match: Match) -> str:
        return "Seed: Pending"

    def build_room_ready_user_text(self, match: Match) -> str:
        return f"Match: {self.build_match_label(match)}"

    def build_room_ready_bot_text(self, match: Match) -> str:
        return f"Seed: {match.seed_value or 'Pending'}"

    async def create_room(self, category_slug: str, goal: str, info_user: str, info_bot: str) -> dict:
        token = await self.get_access_token(category_slug)
        url = f"{self.HTTP_BASE}/o/{category_slug}/startrace"
        ranked = self._is_ranked_goal(goal)

        payload = {
            "goal": goal,
            "invitational": False,
            "unlisted": False,
            "ranked": ranked,
            "info_user": info_user,
            "info_bot": info_bot,
            "start_delay": 15,
        }

        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                data=payload,
            )
            response.raise_for_status()

            location = response.headers.get("Location", "")
            data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}

            room_url = location or data.get("url") or ""
            data["room_url"] = self._full_room_url(room_url)

            websocket_url = data.get("websocket_bot_url") or ""
            data["websocket_bot_url"] = websocket_url

            logger.info(
                "Racetime create_room | category=%s goal=%s room_url=%r websocket=%r unlisted=%s ranked=%s",
                category_slug,
                goal,
                data["room_url"],
                data["websocket_bot_url"],
                payload["unlisted"],
                payload["ranked"],
            )

            return data

    async def create_room_for_match(self, match: Match) -> dict:
        category = self.settings.racetime_categories[match.category_slug]
        return await self.create_room(
            category_slug=match.category_slug,
            goal=match.subcategory or category.default_goal,
            info_user=self.build_room_open_user_text(match),
            info_bot=self.build_room_open_bot_text(match),
        )

    async def fetch_race(self, room_url: str) -> dict:
        full_room_url = self._full_room_url(room_url)
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{full_room_url}/data")
            response.raise_for_status()
            return response.json()

    async def _resolve_match_websocket_url(self, match: Match) -> str:
        websocket_url = getattr(match, "racetime_ws_url", None)

        if not websocket_url and getattr(match, "racetime_room_url", None):
            race_data = await self.fetch_race(match.racetime_room_url)
            websocket_url = (
                race_data.get("websocket_bot_url")
                or race_data.get("bot", {}).get("websocket_bot_url")
                or race_data.get("websocket")
            )

            # Backfill the in-memory object so repeat calls in this run do not rediscover it.
            if websocket_url:
                match.racetime_ws_url = websocket_url

        if not websocket_url:
            raise RuntimeError(f"Match {match.id} has no racetime websocket URL")

        return websocket_url

    async def set_room_info(
        self,
        category_slug: str,
        websocket_url: str,
        info_bot: str,
        info_user: str | None = None,
    ) -> None:
        token = await self.get_access_token(category_slug)
        full_ws_url = self._full_websocket_url(websocket_url, token)

        payload = {
            "action": "setinfo",
            "data": {
                "info_bot": info_bot,
            },
        }
        if info_user is not None:
            payload["data"]["info_user"] = info_user

        logger.info(
            "Racetime setinfo | category=%s ws=%s payload=%s",
            category_slug,
            full_ws_url,
            payload,
        )

        async with websockets.connect(full_ws_url) as ws:
            try:
                initial_message = await asyncio.wait_for(ws.recv(), timeout=10)
                logger.info("Racetime websocket initial message: %s", initial_message)
            except asyncio.TimeoutError:
                logger.info("Racetime websocket initial message timeout")

            await ws.send(json.dumps(payload))
            logger.info("Racetime setinfo sent")

            for idx in range(3):
                try:
                    followup_message = await asyncio.wait_for(ws.recv(), timeout=5)
                    logger.info("Racetime websocket follow-up %s: %s", idx + 1, followup_message)
                except asyncio.TimeoutError:
                    logger.info("Racetime websocket no more follow-up after setinfo")
                    break

    async def update_room_info_for_match(self, match: Match, reveal_seed: bool = True) -> None:
        websocket_url = await self._resolve_match_websocket_url(match)

        info_user = self.build_room_ready_user_text(match)
        info_bot = self.build_room_ready_bot_text(match) if reveal_seed else self.build_room_open_bot_text(match)

        await self.set_room_info(
            category_slug=match.category_slug,
            websocket_url=websocket_url,
            info_user=info_user,
            info_bot=info_bot,
        )