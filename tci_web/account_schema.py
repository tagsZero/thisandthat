"""Shared grants and separate notes; loading this module never changes a database."""
from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String, Table, Text, UniqueConstraint, DateTime

from .db import metadata, utc_now


def one_exam():
    return CheckConstraint(
        "(report_id IS NOT NULL AND job_id IS NULL) OR (report_id IS NULL AND job_id IS NOT NULL)",
        name="one_exam",
    )


exam_shares = Table(
    "exam_shares", metadata,
    Column("id", Integer, primary_key=True),
    Column("report_id", ForeignKey("reports.id", ondelete="CASCADE"), nullable=True),
    Column("job_id", String(36), ForeignKey("khtp_jobs.id", ondelete="CASCADE"), nullable=True),
    Column("recipient_id", ForeignKey("users.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utc_now),
    one_exam(),
    UniqueConstraint("report_id", "recipient_id", name="uq_exam_shares_report_recipient"),
    UniqueConstraint("job_id", "recipient_id", name="uq_exam_shares_job_recipient"),
)
Index("ix_exam_shares_recipient", exam_shares.c.recipient_id)

exam_comments = Table(
    "exam_comments", metadata,
    Column("id", Integer, primary_key=True),
    Column("report_id", ForeignKey("reports.id", ondelete="CASCADE"), nullable=True),
    Column("job_id", String(36), ForeignKey("khtp_jobs.id", ondelete="CASCADE"), nullable=True),
    Column("author_id", ForeignKey("users.id"), nullable=False),
    Column("recipient_id", ForeignKey("users.id"), nullable=True),
    Column("body", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utc_now),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utc_now),
    one_exam(),
)
Index("ix_exam_comments_report_created", exam_comments.c.report_id, exam_comments.c.created_at, exam_comments.c.id)
Index("ix_exam_comments_job_created", exam_comments.c.job_id, exam_comments.c.created_at, exam_comments.c.id)
