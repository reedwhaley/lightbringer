from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import requests

from app.config import Settings


SG_SUCCESS_MARKER = "Match Submission Confirmed"
SG_SUBMITTED_MARKER = "The match has been submitted!"


@dataclass
class SGSubmitResult:
    ok: bool
    status_code: int
    request_url: str
    episode_id: str | None
    message: str
    response_text: str


class SGFormService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _eventslug(self, category_slug: str, is_weekly: bool = False) -> str:
        slug = str(category_slug).lower().strip()

        mapping = {
            ("mpr", False): "mpr",
            ("mpr", True): "mprweekly",
            ("mp2r", False): "mp2",
            ("mp2r", True): "mp2rweekly",
            ("mpcgr", False): "mpcgc",
            ("mpcgr", True): "mpcgcweekly",
        }

        if (slug, is_weekly) not in mapping:
            raise ValueError(f"Unsupported SG category slug: {category_slug}")

        return mapping[(slug, is_weekly)]

    def _submit_url(self, category_slug: str, is_weekly: bool = False) -> str:
        eventslug = self._eventslug(category_slug, is_weekly=is_weekly)
        return f"{self.settings.sg_base_url}/{eventslug}/submit/"

    def _commentator_signup_url(self, episode_id: str | int) -> str:
        return f"{self.settings.sg_base_url}/commentator/signup/{str(episode_id).strip()}/"

    def _tracker_signup_url(self, episode_id: str | int) -> str:
        return f"{self.settings.sg_base_url}/tracker/signup/{str(episode_id).strip()}/"

    def _extract_episode_id(self, html: str) -> str | None:
        match = re.search(r"Episode ID:\s*([0-9]+)", html, flags=re.IGNORECASE)
        return match.group(1) if match else None

    def _extract_csrf_token(self, html: str) -> str | None:
        patterns = [
            r'name="csrfmiddlewaretoken"\s+value="([^"]+)"',
            r'value="([^"]+)"\s+name="csrfmiddlewaretoken"',
            r"name='csrfmiddlewaretoken'\s+value='([^']+)'",
            r"value='([^']+)'\s+name='csrfmiddlewaretoken'",
        ]
        for pattern in patterns:
            match = re.search(pattern, html, flags=re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def _base_headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.settings.sg_user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Connection": "close",
        }

    def _success(self, html: str) -> bool:
        return SG_SUCCESS_MARKER in html and SG_SUBMITTED_MARKER in html

    def _volunteer_success(self, html: str, route_name: str) -> bool:
        text = html or ""
        lowered = text.lower()

        if route_name not in lowered:
            return False

        error_markers = [
            "this field is required",
            "select a valid choice",
            "forbidden",
            "unable to",
            "server error",
            "traceback",
        ]
        if any(marker in lowered for marker in error_markers):
            return False

        return True

    def _friendly_volunteer_error(self, exc: Exception) -> str:
        text = str(exc).lower()
        if "bad signature" in text or "ssl" in text:
            return "Match has not been approved on SpeedGaming. Please try again later."
        return f"SG signup failed: {exc}"

    def _submit_volunteer_form(
        self,
        *,
        submit_url: str,
        route_name: str,
        episode_id: str | int,
        displayname: str,
        discordtag: str,
        publicstream: str,
    ) -> SGSubmitResult:
        try:
            with requests.Session() as session:
                get_response = session.get(
                    submit_url,
                    headers=self._base_headers(),
                    timeout=20,
                    allow_redirects=True,
                )
                get_response.raise_for_status()

                csrf_token = self._extract_csrf_token(get_response.text)

                payload: dict[str, Any] = {
                    "episodeid": str(episode_id).strip(),
                    "personid": "0",
                    "discordtag": str(discordtag),
                    "displayname": str(displayname),
                    "publicstream": str(publicstream),
                    "submit": "Submit New/Updated Info",
                }

                if csrf_token:
                    payload["csrfmiddlewaretoken"] = csrf_token

                post_headers = {
                    **self._base_headers(),
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": self.settings.sg_base_url,
                    "Referer": submit_url,
                }

                post_response = session.post(
                    submit_url,
                    data=payload,
                    headers=post_headers,
                    timeout=20,
                    allow_redirects=True,
                )

                text = post_response.text or ""
                ep_id = str(episode_id).strip()

                if post_response.status_code != 200:
                    return SGSubmitResult(
                        ok=False,
                        status_code=post_response.status_code,
                        request_url=submit_url,
                        episode_id=ep_id,
                        message=f"HTTP {post_response.status_code}",
                        response_text=text,
                    )

                if not self._volunteer_success(text, route_name):
                    return SGSubmitResult(
                        ok=False,
                        status_code=post_response.status_code,
                        request_url=submit_url,
                        episode_id=ep_id,
                        message="Match has not been approved on SpeedGaming. Please try again later.",
                        response_text=text,
                    )

                return SGSubmitResult(
                    ok=True,
                    status_code=post_response.status_code,
                    request_url=submit_url,
                    episode_id=ep_id,
                    message=f"SG {route_name} signup submitted successfully.",
                    response_text=text,
                )
        except requests.RequestException as exc:
            return SGSubmitResult(
                ok=False,
                status_code=0,
                request_url=submit_url,
                episode_id=str(episode_id).strip(),
                message=self._friendly_volunteer_error(exc),
                response_text="",
            )

    def submit_standard_match(
        self,
        *,
        category_slug: str,
        displayname1: str,
        displayname2: str,
        discordtag1: str,
        discordtag2: str,
        publicstream1: str,
        publicstream2: str,
        whendate: str,
        whentime: str,
        whenampm: str,
        note: str = "",
        is_weekly: bool = False,
    ) -> SGSubmitResult:
        submit_url = self._submit_url(category_slug, is_weekly=is_weekly)

        with requests.Session() as session:
            get_response = session.get(
                submit_url,
                headers=self._base_headers(),
                timeout=20,
                allow_redirects=True,
            )
            get_response.raise_for_status()

            csrf_token = self._extract_csrf_token(get_response.text)

            payload: dict[str, Any] = {
                "eventslug": self._eventslug(category_slug, is_weekly=is_weekly),
                "person1id": "0",
                "discordtag1": str(discordtag1),
                "displayname1": str(displayname1),
                "publicstream1": str(publicstream1),
                "person2id": "0",
                "discordtag2": str(discordtag2),
                "displayname2": str(displayname2),
                "publicstream2": str(publicstream2),
                "whendate": str(whendate),
                "whentime": str(whentime),
                "whenampm": str(whenampm).lower(),
                "whentimezone": "",
                "note": str(note),
                "submit": "Submit Match",
            }

            if csrf_token:
                payload["csrfmiddlewaretoken"] = csrf_token

            post_headers = {
                **self._base_headers(),
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": self.settings.sg_base_url,
                "Referer": submit_url,
            }

            post_response = session.post(
                submit_url,
                data=payload,
                headers=post_headers,
                timeout=20,
                allow_redirects=True,
            )

            text = post_response.text or ""
            episode_id = self._extract_episode_id(text)

            if post_response.status_code != 200:
                return SGSubmitResult(
                    ok=False,
                    status_code=post_response.status_code,
                    request_url=submit_url,
                    episode_id=episode_id,
                    message=f"HTTP {post_response.status_code}",
                    response_text=text,
                )

            if not self._success(text):
                return SGSubmitResult(
                    ok=False,
                    status_code=post_response.status_code,
                    request_url=submit_url,
                    episode_id=episode_id,
                    message="Response did not contain SG success markers.",
                    response_text=text,
                )

            msg = "SG match submitted successfully."
            if episode_id:
                msg += f" Episode ID: {episode_id}."

            return SGSubmitResult(
                ok=True,
                status_code=post_response.status_code,
                request_url=submit_url,
                episode_id=episode_id,
                message=msg,
                response_text=text,
            )

    def submit_cgc_match(
        self,
        *,
        category_slug: str,
        displayname1: str,
        displayname2: str,
        displayname3: str,
        displayname4: str,
        discordtag1: str,
        discordtag2: str,
        discordtag3: str,
        discordtag4: str,
        publicstream1: str,
        publicstream2: str,
        publicstream3: str,
        publicstream4: str,
        whendate: str,
        whentime: str,
        whenampm: str,
        note: str = "",
        is_weekly: bool = False,
    ) -> SGSubmitResult:
        submit_url = self._submit_url(category_slug, is_weekly=is_weekly)

        with requests.Session() as session:
            get_response = session.get(
                submit_url,
                headers=self._base_headers(),
                timeout=20,
                allow_redirects=True,
            )
            get_response.raise_for_status()

            csrf_token = self._extract_csrf_token(get_response.text)

            payload: dict[str, Any] = {
                "eventslug": self._eventslug(category_slug, is_weekly=is_weekly),
                "person1id": "0",
                "discordtag1": str(discordtag1),
                "displayname1": str(displayname1),
                "publicstream1": str(publicstream1),
                "person2id": "0",
                "discordtag2": str(discordtag2),
                "displayname2": str(displayname2),
                "publicstream2": str(publicstream2),
                "person3id": "0",
                "discordtag3": str(discordtag3),
                "displayname3": str(displayname3),
                "publicstream3": str(publicstream3),
                "person4id": "0",
                "discordtag4": str(discordtag4),
                "displayname4": str(displayname4),
                "publicstream4": str(publicstream4),
                "whendate": str(whendate),
                "whentime": str(whentime),
                "whenampm": str(whenampm).lower(),
                "whentimezone": "",
                "note": str(note),
                "submit": "Submit Match",
            }

            if csrf_token:
                payload["csrfmiddlewaretoken"] = csrf_token

            post_headers = {
                **self._base_headers(),
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": self.settings.sg_base_url,
                "Referer": submit_url,
            }

            post_response = session.post(
                submit_url,
                data=payload,
                headers=post_headers,
                timeout=20,
                allow_redirects=True,
            )

            text = post_response.text or ""
            episode_id = self._extract_episode_id(text)

            if post_response.status_code != 200:
                return SGSubmitResult(
                    ok=False,
                    status_code=post_response.status_code,
                    request_url=submit_url,
                    episode_id=episode_id,
                    message=f"HTTP {post_response.status_code}",
                    response_text=text,
                )

            if not self._success(text):
                return SGSubmitResult(
                    ok=False,
                    status_code=post_response.status_code,
                    request_url=submit_url,
                    episode_id=episode_id,
                    message="Response did not contain SG success markers.",
                    response_text=text,
                )

            msg = "SG CGC match submitted successfully."
            if episode_id:
                msg += f" Episode ID: {episode_id}."

            return SGSubmitResult(
                ok=True,
                status_code=post_response.status_code,
                request_url=submit_url,
                episode_id=episode_id,
                message=msg,
                response_text=text,
            )

    def submit_commentator_signup(
        self,
        *,
        episode_id: str | int,
        displayname: str,
        discordtag: str,
        publicstream: str,
    ) -> SGSubmitResult:
        return self._submit_volunteer_form(
            submit_url=self._commentator_signup_url(episode_id),
            route_name="commentator",
            episode_id=episode_id,
            displayname=displayname,
            discordtag=discordtag,
            publicstream=publicstream,
        )

    def submit_tracker_signup(
        self,
        *,
        episode_id: str | int,
        displayname: str,
        discordtag: str,
        publicstream: str,
    ) -> SGSubmitResult:
        return self._submit_volunteer_form(
            submit_url=self._tracker_signup_url(episode_id),
            route_name="tracker",
            episode_id=episode_id,
            displayname=displayname,
            discordtag=discordtag,
            publicstream=publicstream,
        )