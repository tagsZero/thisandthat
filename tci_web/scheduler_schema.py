"""Schedule grants and conversations, separate from examination contracts."""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, Table, Text, UniqueConstraint

from .db import metadata, utc_now


appointment_shares = Table(
    "appointment_shares", metadata,
    Column("id", Integer, primary_key=True),
    Column("appointment_id", ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False),
    Column("recipient_id", ForeignKey("users.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utc_now),
    UniqueConstraint("appointment_id", "recipient_id", name="uq_appointment_shares_recipient"),
)
Index("ix_appointment_shares_recipient", appointment_shares.c.recipient_id)

appointment_comments = Table(
    "appointment_comments", metadata,
    Column("id", Integer, primary_key=True),
    Column("appointment_id", ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False),
    Column("author_id", ForeignKey("users.id"), nullable=False),
    Column("recipient_id", ForeignKey("users.id"), nullable=True),
    Column("body", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utc_now),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utc_now),
)
Index("ix_appointment_comments_created", appointment_comments.c.appointment_id,
      appointment_comments.c.created_at, appointment_comments.c.id)
