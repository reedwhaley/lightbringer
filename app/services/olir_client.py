from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings


class OLirClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.olir_internal_api_token}",
            "Content-Type": "application/json",
        }

    async def fetch_speedgaming_profile(self, discord_id: str) -> dict[str, Any]:
        url = f"{self.settings.olir_api_base_url}/speedgaming_profiles/{discord_id}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            return response.json()

    async def fetch_entrant_identities(self, entrant_id: str) -> dict[str, Any]:
        url = f"{self.settings.olir_api_base_url}/identities/entrant/{entrant_id}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            return response.json()

    async def get_pairing_by_thread(self, thread_id: str) -> dict[str, Any]:
        url = f"{self.settings.olir_api_base_url}/pairings/by-thread/{thread_id}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            return response.json()

    async def link_lightbringer_match(
        self,
        *,
        pairing_id: str,
        lightbringer_match_id: str,
        start_at_utc: str,
    ) -> dict[str, Any]:
        url = f"{self.settings.olir_api_base_url}/pairings/{pairing_id}/link-lightbringer-match"
        payload = {
            "lightbringer_match_id": str(lightbringer_match_id),
            "start_at_utc": str(start_at_utc),
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, headers=self._headers(), json=payload)
            response.raise_for_status()
            return response.json()

    async def report_match_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.settings.olir_api_base_url}/pairings/report-lightbringer-result"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, headers=self._headers(), json=payload)
            response.raise_for_status()
            return response.json()