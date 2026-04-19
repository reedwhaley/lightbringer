from __future__ import annotations

import secrets


def make_match_id(category_slug: str) -> str:
    return f"{category_slug.upper()}-{secrets.token_hex(3).upper()}"
