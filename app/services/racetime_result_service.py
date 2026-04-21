from __future__ import annotations

import json
from typing import Any


class RacetimeResultService:
    def _norm(self, value: str | None) -> str:
        return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())

    def _display_name(self, entrant: dict[str, Any]) -> str:
        user = entrant.get("user") or {}
        return (
            entrant.get("display_name")
            or entrant.get("name")
            or user.get("full_name")
            or user.get("display_name")
            or user.get("name")
            or user.get("username")
            or "Unknown"
        )

    def _status_value(self, entrant: dict[str, Any]) -> str:
        status = entrant.get("status")
        if isinstance(status, dict):
            return str(status.get("value") or status.get("name") or "").strip().lower()
        return str(status or "").strip().lower()

    def _placement(self, entrant: dict[str, Any]) -> int | None:
        for key in ("place", "placement", "rank"):
            value = entrant.get(key)
            if value is not None:
                try:
                    return int(value)
                except Exception:
                    pass
        status = entrant.get("status") or {}
        if isinstance(status, dict):
            for key in ("place", "placement", "rank"):
                value = status.get(key)
                if value is not None:
                    try:
                        return int(value)
                    except Exception:
                        pass
        return None

    def _finish_seconds(self, entrant: dict[str, Any]) -> float | None:
        candidates = [
            entrant.get("finish_time_seconds"),
            entrant.get("finish_time_raw"),
            entrant.get("finish_seconds"),
            entrant.get("time_seconds"),
        ]
        status = entrant.get("status") or {}
        if isinstance(status, dict):
            candidates.extend(
                [
                    status.get("finish_time_seconds"),
                    status.get("finish_time_raw"),
                    status.get("finish_seconds"),
                ]
            )
        for value in candidates:
            if value is None:
                continue
            try:
                return float(value)
            except Exception:
                continue
        milliseconds = entrant.get("finish_time_ms")
        if milliseconds is not None:
            try:
                return float(milliseconds) / 1000.0
            except Exception:
                pass
        return None

    def _finish_text(self, entrant: dict[str, Any], seconds: float | None) -> str | None:
        for key in ("finish_time", "finish_time_text", "time", "time_text"):
            value = entrant.get(key)
            if value:
                return str(value)
        status = entrant.get("status") or {}
        if isinstance(status, dict):
            for key in ("finish_time", "finish_time_text", "time", "time_text"):
                value = status.get(key)
                if value:
                    return str(value)
        if seconds is None:
            return None
        total = int(round(seconds))
        hours = total // 3600
        minutes = (total % 3600) // 60
        secs = total % 60
        if hours:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    def _entrant_payload(self, entrant: dict[str, Any]) -> dict[str, Any]:
        seconds = self._finish_seconds(entrant)
        return {
            "name": self._display_name(entrant),
            "finish_time_seconds": seconds,
            "finish_time_text": self._finish_text(entrant, seconds),
            "placement": self._placement(entrant),
            "status": self._status_value(entrant),
        }

    def _completed_entrants(self, race_data: dict[str, Any]) -> list[dict[str, Any]]:
        entrants = list(race_data.get("entrants") or [])
        payloads = [self._entrant_payload(e) | {"_raw": e} for e in entrants]
        payloads.sort(key=lambda e: (e["placement"] if e["placement"] is not None else 999999, e["finish_time_seconds"] if e["finish_time_seconds"] is not None else 1e18, e["name"].lower()))
        return payloads

    def _find_by_expected_names(self, entrants: list[dict[str, Any]], expected_names: list[str]) -> list[dict[str, Any]]:
        wanted = {self._norm(name) for name in expected_names if name}
        found: list[dict[str, Any]] = []
        for entrant in entrants:
            entrant_norm = self._norm(entrant["name"])
            if entrant_norm in wanted:
                found.append(entrant)
        return found

    def _average_team_time(self, entrants: list[dict[str, Any]]) -> tuple[float | None, str | None]:
        times = [e["finish_time_seconds"] for e in entrants if e.get("finish_time_seconds") is not None]
        if len(times) < 2:
            return None, None
        average = sum(times) / 2.0
        total = int(round(average))
        hours = total // 3600
        minutes = (total % 3600) // 60
        secs = total % 60
        if hours:
            text = f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            text = f"{minutes}:{secs:02d}"
        return average, text

    def build_olir_result_payload(self, match: Any, race_data: dict[str, Any]) -> dict[str, Any] | None:
        entrants = self._completed_entrants(race_data)
        if not entrants:
            return None

        completed_at = race_data.get("opened_at") or race_data.get("ended_at") or race_data.get("updated_at")
        room_url = getattr(match, "racetime_room_url", None)

        if str(getattr(match, "category_slug", "")).lower() == "mpcgr":
            team1_members = [getattr(match, "team1_player1_name", None), getattr(match, "team1_player2_name", None)]
            team2_members = [getattr(match, "team2_player1_name", None), getattr(match, "team2_player2_name", None)]

            team1_entrants = self._find_by_expected_names(entrants, team1_members)
            team2_entrants = self._find_by_expected_names(entrants, team2_members)

            if len(team1_entrants) < 2 or len(team2_entrants) < 2:
                return None

            team1_seconds, team1_text = self._average_team_time(team1_entrants)
            team2_seconds, team2_text = self._average_team_time(team2_entrants)
            if team1_seconds is None or team2_seconds is None:
                return None

            winner_side = "team1" if team1_seconds <= team2_seconds else "team2"

            return {
                "lightbringer_match_id": getattr(match, "id", ""),
                "race_room_url": room_url,
                "completed_at_utc": completed_at,
                "result_source": "racetime",
                "status": "finished",
                "winner_side": winner_side,
                "team1": {
                    "name": getattr(match, "team1", "Team 1"),
                    "finish_time_seconds": team1_seconds,
                    "finish_time_text": team1_text,
                    "placement": 1 if winner_side == "team1" else 2,
                    "status": "done",
                    "member_names": [e["name"] for e in team1_entrants],
                },
                "team2": {
                    "name": getattr(match, "team2", "Team 2"),
                    "finish_time_seconds": team2_seconds,
                    "finish_time_text": team2_text,
                    "placement": 1 if winner_side == "team2" else 2,
                    "status": "done",
                    "member_names": [e["name"] for e in team2_entrants],
                },
                "raw_result_json": race_data,
            }

        expected_team1 = self._norm(getattr(match, "team1", None))
        expected_team2 = self._norm(getattr(match, "team2", None))
        team1_payload = None
        team2_payload = None

        for entrant in entrants:
            norm_name = self._norm(entrant["name"])
            if expected_team1 and norm_name == expected_team1 and team1_payload is None:
                team1_payload = {k: v for k, v in entrant.items() if k != "_raw"}
            elif expected_team2 and norm_name == expected_team2 and team2_payload is None:
                team2_payload = {k: v for k, v in entrant.items() if k != "_raw"}

        if team1_payload is None or team2_payload is None:
            done = [{k: v for k, v in e.items() if k != "_raw"} for e in entrants[:2]]
            if len(done) < 2:
                return None
            team1_payload = team1_payload or done[0]
            team2_payload = team2_payload or done[1]

        winner_side = "team1"
        if (team2_payload.get("placement") or 999999) < (team1_payload.get("placement") or 999999):
            winner_side = "team2"
        elif team1_payload.get("finish_time_seconds") is not None and team2_payload.get("finish_time_seconds") is not None:
            winner_side = "team1" if team1_payload["finish_time_seconds"] <= team2_payload["finish_time_seconds"] else "team2"

        payload = {
            "lightbringer_match_id": getattr(match, "id", ""),
            "race_room_url": room_url,
            "completed_at_utc": completed_at,
            "result_source": "racetime",
            "status": "finished",
            "winner_side": winner_side,
            "team1": team1_payload,
            "team2": team2_payload,
            "raw_result_json": race_data,
        }

        # keep JSON-safe if caller serializes directly with standard json
        json.dumps(payload, default=str)
        return payload
