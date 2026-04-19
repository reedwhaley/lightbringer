from __future__ import annotations

from sqlalchemy import delete, select

from app.models import MessageLog, ReminderLog


class ReminderService:
    def already_sent(self, session, match_id: str, reminder_type: str) -> bool:
        stmt = select(ReminderLog).where(
            ReminderLog.match_id == match_id,
            ReminderLog.reminder_type == reminder_type,
        )
        return session.execute(stmt).scalar_one_or_none() is not None

    def mark_sent(self, session, match_id: str, reminder_type: str) -> None:
        if self.already_sent(session, match_id, reminder_type):
            return
        session.add(ReminderLog(match_id=match_id, reminder_type=reminder_type))

    def track_message(self, session, match_id: str, message_type: str, channel_id: int, message_id: int) -> None:
        stmt = select(MessageLog).where(
            MessageLog.match_id == match_id,
            MessageLog.message_type == message_type,
            MessageLog.channel_id == str(channel_id),
            MessageLog.message_id == str(message_id),
        )
        existing = session.execute(stmt).scalar_one_or_none()
        if existing:
            return

        session.add(
            MessageLog(
                match_id=match_id,
                message_type=message_type,
                channel_id=str(channel_id),
                message_id=str(message_id),
            )
        )

    def get_tracked_messages(self, session, match_id: str, message_types: list[str] | None = None) -> list[MessageLog]:
        stmt = select(MessageLog).where(MessageLog.match_id == match_id)
        if message_types:
            stmt = stmt.where(MessageLog.message_type.in_(message_types))
        return list(session.execute(stmt).scalars().all())

    def get_tracked_messages_excluding(self, session, match_id: str, excluded_types: list[str] | None = None) -> list[MessageLog]:
        stmt = select(MessageLog).where(MessageLog.match_id == match_id)
        if excluded_types:
            stmt = stmt.where(~MessageLog.message_type.in_(excluded_types))
        return list(session.execute(stmt).scalars().all())

    def delete_tracked_messages(self, session, match_id: str, message_types: list[str] | None = None) -> None:
        stmt = delete(MessageLog).where(MessageLog.match_id == match_id)
        if message_types:
            stmt = stmt.where(MessageLog.message_type.in_(message_types))
        session.execute(stmt)

    def delete_tracked_messages_excluding(self, session, match_id: str, excluded_types: list[str] | None = None) -> None:
        stmt = delete(MessageLog).where(MessageLog.match_id == match_id)
        if excluded_types:
            stmt = stmt.where(~MessageLog.message_type.in_(excluded_types))
        session.execute(stmt)

    def delete_specific_message(self, session, match_id: str, message_type: str) -> None:
        stmt = delete(MessageLog).where(
            MessageLog.match_id == match_id,
            MessageLog.message_type == message_type,
        )
        session.execute(stmt)