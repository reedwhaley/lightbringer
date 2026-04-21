from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import Settings


@dataclass
class TwitchStreamInfo:
    user_login: str
    title: str
    game_name: str
    url: str


class TwitchService:
    SG_CHANNELS = [
        "speedgaming",
        "speedgaming2",
        "speedgaming3",
        "speedgaming4",
        "speedgaming5",
        "speedgaming6",
        "speedgaming7",
    ]

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._app_token: str | None = None
        self._app_token_expires_at: float = 0.0

    def enabled(self) -> bool:
        return bool(self.settings.twitch_client_id and self.settings.twitch_client_secret)

    async def _ensure_token(self) -> str:
        if self._app_token and time.time() < self._app_token_expires_at - 60:
            return self._app_token

        if not self.enabled():
            raise RuntimeError("Twitch API is not configured.")

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://id.twitch.tv/oauth2/token",
                params={
                    "client_id": self.settings.twitch_client_id,
                    "client_secret": self.settings.twitch_client_secret,
                    "grant_type": "client_credentials",
                },
            )
            response.raise_for_status()
            data = response.json()

        self._app_token = str(data["access_token"])
        expires_in = int(data.get("expires_in", 0))
        self._app_token_expires_at = time.time() + expires_in
        return self._app_token

    async def _headers(self) -> dict[str, str]:
        token = await self._ensure_token()
        return {
            "Client-Id": self.settings.twitch_client_id,
            "Authorization": f"Bearer {token}",
        }

    async def get_live_speedgaming_streams(self) -> list[TwitchStreamInfo]:
        if not self.enabled():
            return []

        query = urlencode([("user_login", login) for login in self.SG_CHANNELS])
        url = f"https://api.twitch.tv/helix/streams?{query}"

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=await self._headers())
            response.raise_for_status()
            payload = response.json()

        streams: list[TwitchStreamInfo] = []
        for row in payload.get("data", []):
            user_login = str(row.get("user_login", "")).strip().lower()
            streams.append(
                TwitchStreamInfo(
                    user_login=user_login,
                    title=str(row.get("title", "")).strip(),
                    game_name=str(row.get("game_name", "")).strip(),
                    url=f"https://twitch.tv/{user_login}",
                )
            )
        return streams

    def find_best_match(self, match, streams: list[TwitchStreamInfo]) -> TwitchStreamInfo | None:
        candidates: list[tuple[int, TwitchStreamInfo]] = []

        team1 = str(getattr(match, "team1", "") or "").strip().lower()
        team2 = str(getattr(match, "team2", "") or "").strip().lower()
        stream_name = str(getattr(match, "stream_name", "") or "").strip().lower()
        category_slug = str(getattr(match, "category_slug", "") or "").strip().lower()

        for stream in streams:
            haystack = f"{stream.title} {stream.game_name}".lower()
            score = 0

            if "metroid prime" in haystack:
                score += 3
            if category_slug and category_slug in haystack:
                score += 1
            if stream_name and stream_name in haystack:
                score += 3
            if team1 and team1 in haystack:
                score += 3
            if team2 and team2 in haystack:
                score += 3
            if team1 and team2 and f"{team1} vs {team2}" in haystack:
                score += 4
            if team1 and team2 and f"{team1} v {team2}" in haystack:
                score += 4

            if score > 0:
                candidates.append((score, stream))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0], reverse=True)
        best_score, best_stream = candidates[0]

        if best_score < 4:
            return None

        if len(candidates) > 1 and candidates[1][0] == best_score:
            return None

        return best_stream
