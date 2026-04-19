from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Integer, DateTime, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    category_slug: Mapped[str] = mapped_column(String(16), index=True)
    subcategory: Mapped[str] = mapped_column(String(100), default="tournament")

    team1: Mapped[str] = mapped_column(String(150))
    team2: Mapped[str] = mapped_column(String(150))

    entrant1_discord_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entrant2_discord_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    team1_player1_discord_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    team1_player2_discord_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    team2_player1_discord_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    team2_player2_discord_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    team1_player1_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    team1_player2_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    team2_player1_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    team2_player2_name: Mapped[str | None] = mapped_column(String(150), nullable=True)

    team1_room_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    team2_room_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    team1_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    team2_password: Mapped[str | None] = mapped_column(String(255), nullable=True)

    stream_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    speedgaming_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="open")
    seed_status: Mapped[str] = mapped_column(String(32), default="pending")
    seed_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    assigned_discord_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    assigned_display_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_by_discord_id: Mapped[str] = mapped_column(String(32))

    start_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    setup_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    room_open_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    seed_prompt_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)

    setup_complete: Mapped[bool] = mapped_column(Boolean, default=False)

    calendar_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    discord_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    racetime_room_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    racetime_race_slug: Mapped[str | None] = mapped_column(String(255), nullable=True)
    racetime_ws_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    claim_channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    claim_message_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class ReminderLog(Base):
    __tablename__ = "reminder_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(String(32), index=True)
    reminder_type: Mapped[str] = mapped_column(String(32), index=True)
    sent_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)


class MessageLog(Base):
    __tablename__ = "message_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(String(32), index=True)
    message_type: Mapped[str] = mapped_column(String(64), index=True)
    channel_id: Mapped[str] = mapped_column(String(32), index=True)
    message_id: Mapped[str] = mapped_column(String(32), index=True)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)