from datetime import datetime, timezone

import click
from flask import current_app
from sqlalchemy import (
    JSON, Boolean, Column, Date, DateTime, ForeignKey, Integer, MetaData,
    String, Table, Text, Time, Index, UniqueConstraint, CheckConstraint, select, inspect, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from werkzeug.security import generate_password_hash

metadata = MetaData()
json_type = JSON().with_variant(JSONB, "postgresql")


def utc_now():
    return datetime.now(timezone.utc)


users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(80), unique=True, nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("is_admin", Boolean, nullable=False, default=False, server_default=text("false")),
    Column("is_active", Boolean, nullable=False, default=True, server_default=text("true")),
    Column("session_version", Integer, nullable=False, default=0, server_default=text("0")),
    Column("next_person_code", Integer, nullable=False, default=0, server_default=text("0")),
)
feature_settings = Table(
    "feature_settings", metadata,
    Column("key", String(30), primary_key=True),
    Column("enabled", Boolean, nullable=False, default=True, server_default=text("true")),
)
people = Table(
    "people", metadata,
    Column("id", Integer, primary_key=True),
    Column("owner_id", ForeignKey("users.id"), nullable=False),
    Column("code", Integer, nullable=False),
    Column("name", String(100), nullable=False, default=""),
    Column("reference", String(100), nullable=False, default=""),
    Column("registered_on", Date, nullable=False),
    Column("merged_into_id", ForeignKey("people.id"), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utc_now),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utc_now),
    UniqueConstraint("owner_id", "code", name="uq_people_owner_code"),
    CheckConstraint("code > 0", name="ck_people_positive_code"),
    CheckConstraint("merged_into_id IS NULL OR merged_into_id != id", name="ck_people_not_self_merged"),
)
Index("ix_people_owner_name", people.c.owner_id, people.c.name, people.c.id)
reports = Table(
    "reports", metadata,
    Column("id", Integer, primary_key=True),
    Column("owner_id", ForeignKey("users.id"), nullable=True),
    Column("person_id", ForeignKey("people.id"), nullable=True),
    Column("name", String(100), nullable=False, default=""),
    Column("reference", String(100), nullable=False, default=""),
    Column("exam_date", Date),
    Column("scores", json_type, nullable=False),
    Column("settings", json_type, nullable=False),
    Column("body", Text, nullable=False, default=""),
    Column("composition", json_type, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utc_now),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utc_now),
)
appointments = Table(
    "appointments", metadata,
    Column("id", Integer, primary_key=True),
    Column("owner_id", ForeignKey("users.id"), nullable=True),
    Column("day", Date, nullable=False),
    Column("time", Time, nullable=False),
    Column("title", String(120), nullable=False),
    Column("note", Text, nullable=False, default=""),
    Column("report_id", ForeignKey("reports.id"), nullable=True),
    Column("person_id", ForeignKey("people.id"), nullable=True),
    Column("job_id", String(36), ForeignKey("khtp_jobs.id"), nullable=True),
    Column("duration_minutes", Integer, nullable=True),
    Column("status", String(20), nullable=False, default="scheduled", server_default="scheduled"),
    Column("revision", Integer, nullable=False, default=1, server_default=text("1")),
    Column("updated_at", DateTime(timezone=True), nullable=True, default=utc_now),
)
Index("ix_reports_owner_updated_id", reports.c.owner_id, reports.c.updated_at.desc(), reports.c.id.desc())
Index("ix_appointments_owner_day_time", appointments.c.owner_id, appointments.c.day, appointments.c.time)
Index("ix_reports_owner_person", reports.c.owner_id, reports.c.person_id)
Index("ix_appointments_owner_person", appointments.c.owner_id, appointments.c.person_id)

sources = Table(
    "interpretation_sources", metadata,
    Column("id", Integer, primary_key=True),
    Column("seed_key", String(100), unique=True),
    Column("title", Text, nullable=False),
    Column("author", Text, nullable=False, default=""),
    Column("perspective", Text, nullable=False, default=""),
    Column("filename", Text, nullable=False),
    Column("alternate_filename", Text, nullable=False, default=""),
    Column("edition", String(30), nullable=False),
    Column("scope", Text, nullable=False),
    Column("active", Boolean, nullable=False, default=True),
)
interpretations = Table(
    "interpretations", metadata,
    Column("id", Integer, primary_key=True),
    Column("seed_key", String(100), unique=True),
    Column("source_id", ForeignKey("interpretation_sources.id"), nullable=False),
    Column("title", Text, nullable=False),
    Column("section", String(40), nullable=False),
    Column("perspective", Text, nullable=False),
    Column("location", Text, nullable=False),
    Column("original", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("edition", String(30), nullable=False),
    Column("scope", Text, nullable=False),
    Column("related_scales", json_type, nullable=False),
    Column("related_type", json_type, nullable=False),
    Column("conditions", json_type, nullable=False),
    Column("original_criteria", Text, nullable=False),
    Column("sort_order", Integer, nullable=False, default=0),
    Column("group_key", Text, nullable=False, default=""),
    Column("selection", json_type, nullable=True),
    Column("conflict", Text, nullable=False, default=""),
    Column("active", Boolean, nullable=False, default=True),
)


def get_engine():
    return current_app.extensions["db_engine"]


def upgrade_privacy(connection):
    """Explicit, additive preparation. Legacy rows deliberately remain unowned."""
    from . import account_schema  # register the shared tables without startup DDL

    inspector = inspect(connection)
    existing = set(inspector.get_table_names())
    if connection.dialect.name == "postgresql":
        names = [name for name in ("reports", "appointments") if name in existing]
        if names:
            connection.execute(text("LOCK TABLE " + ", ".join(names) + " IN ACCESS EXCLUSIVE MODE"))
    changed = []
    for table in (reports, appointments):
        if table.name in existing:
            columns = {column["name"] for column in inspect(connection).get_columns(table.name)}
            if "owner_id" not in columns:
                connection.execute(text(f"ALTER TABLE {table.name} ADD COLUMN owner_id INTEGER REFERENCES users(id)"))
                changed.append(table.name + ".owner_id")
    metadata.create_all(connection)
    for table in (reports, appointments):
        columns = {column["name"] for column in inspect(connection).get_columns(table.name)}
        for index in table.indexes:
            if all(column.name in columns for column in index.columns):
                index.create(connection, checkfirst=True)
    return changed


def upgrade_haeseok(connection):
    """Add identity/scheduling columns explicitly; never infer legacy identities."""
    from khtp_web import jobs  # register all FK targets before creating tables
    from . import account_schema, scheduler_schema

    existing = set(inspect(connection).get_table_names())
    if connection.dialect.name == "postgresql":
        names = [name for name in ("users", "reports", "khtp_jobs", "appointments") if name in existing]
        if names:
            connection.execute(text("LOCK TABLE " + ", ".join(names) + " IN ACCESS EXCLUSIVE MODE"))
    changed = []

    def add_columns(table_name, definitions):
        if table_name not in existing:
            return
        columns = {column["name"] for column in inspect(connection).get_columns(table_name)}
        for name, definition in definitions:
            if name not in columns:
                # Both names and SQL definitions are fixed constants below.
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}"))
                changed.append(f"{table_name}.{name}")

    add_columns("users", (
        ("is_admin", "BOOLEAN NOT NULL DEFAULT false"),
        ("is_active", "BOOLEAN NOT NULL DEFAULT true"),
        ("session_version", "INTEGER NOT NULL DEFAULT 0"),
        ("next_person_code", "INTEGER NOT NULL DEFAULT 0"),
    ))
    users.create(connection, checkfirst=True)
    people.create(connection, checkfirst=True)
    feature_settings.create(connection, checkfirst=True)
    add_columns("reports", (
        ("owner_id", "INTEGER REFERENCES users(id)"),
        ("person_id", "INTEGER REFERENCES people(id)"),
    ))
    add_columns("khtp_jobs", (("person_id", "INTEGER REFERENCES people(id)"),))
    jobs.create(connection, checkfirst=True)
    stamp_type = "TIMESTAMP WITH TIME ZONE" if connection.dialect.name == "postgresql" else "DATETIME"
    add_columns("appointments", (
        ("owner_id", "INTEGER REFERENCES users(id)"),
        ("person_id", "INTEGER REFERENCES people(id)"),
        ("job_id", "VARCHAR(36) REFERENCES khtp_jobs(id)"),
        ("duration_minutes", "INTEGER"),
        ("status", "VARCHAR(20) NOT NULL DEFAULT 'scheduled'"),
        ("revision", "INTEGER NOT NULL DEFAULT 1"),
        ("updated_at", stamp_type),
    ))
    metadata.create_all(connection)
    for table in (people, reports, appointments, jobs):
        columns = {column["name"] for column in inspect(connection).get_columns(table.name)}
        for index in table.indexes:
            if all(column.name in columns for column in index.columns):
                index.create(connection, checkfirst=True)
    keys = set(connection.scalars(select(feature_settings.c.key)))
    for key in ("tci", "khtp", "schedule"):
        if key not in keys:
            connection.execute(feature_settings.insert().values(key=key, enabled=True))
    return changed


def init_app(app):
    @app.cli.command("upgrade-haeseok")
    def upgrade_haeseok_command():
        """대상자·일정·관리 구조만 준비한다. 기존 자료는 자동 병합하지 않는다."""
        with get_engine().begin() as connection:
            changed = upgrade_haeseok(connection)
        click.echo("해석 구조 준비 완료 · 기존 내용/소유권 보존 · 대상자 자동 연결 없음 · 기존 일정 소요 시간 미설정" +
                   (" · " + ", ".join(changed) if changed else " · 추가 컬럼 변경 없음"))

    @app.cli.command("upgrade-privacy")
    def upgrade_privacy_command():
        """계정 컬럼과 공유/댓글 구조만 준비한다. 기존 소유자는 추측하지 않는다."""
        with get_engine().begin() as connection:
            changed = upgrade_privacy(connection)
        click.echo("계정/공유 구조 준비 완료 · 기존 자료는 미귀속 유지" + (" · " + ", ".join(changed) if changed else " · 반복 적용 변경 없음"))

    @app.cli.command("assign-legacy-owner")
    @click.option("--username", required=True)
    @click.option("--report-id", "report_ids", multiple=True, type=click.IntRange(min=1))
    @click.option("--appointment-id", "appointment_ids", multiple=True, type=click.IntRange(min=1))
    @click.option("--all-unassigned", is_flag=True, help="명시 계정에 모든 미귀속 검사/일정 귀속")
    @click.option("--apply", "apply_changes", is_flag=True, help="지정한 미귀속 행만 실제 귀속")
    def assign_legacy_owner(username, report_ids, appointment_ids, all_unassigned, apply_changes):
        """기본은 점검. 다른 계정의 소유권이나 본문/점수는 변경하지 않는다."""
        from .permissions import readable_condition

        if all_unassigned and (report_ids or appointment_ids):
            raise click.ClickException("--all-unassigned는 개별 ID 옵션과 함께 사용할 수 없습니다.")
        if not all_unassigned and not report_ids and not appointment_ids:
            raise click.ClickException("--report-id, --appointment-id 또는 --all-unassigned를 명시해 주세요.")
        with get_engine().begin() as connection:
            account_id = connection.scalar(select(users.c.id).where(users.c.username == username.strip()))
            if account_id is None:
                raise click.ClickException("존재하지 않는 로그인 아이디입니다.")
            targets = []
            for table, identifiers in ((reports, set(report_ids)), (appointments, set(appointment_ids))):
                if not all_unassigned and not identifiers:
                    continue
                predicate = table.c.owner_id.is_(None) if all_unassigned else table.c.id.in_(identifiers)
                columns = [table.c.id, table.c.owner_id]
                if table is appointments:
                    columns.append(table.c.report_id)
                statement = select(*columns).where(predicate).order_by(table.c.id)
                if apply_changes:
                    statement = statement.with_for_update()
                rows = connection.execute(statement).mappings().all()
                if not all_unassigned and len(rows) != len(identifiers):
                    raise click.ClickException(f"없는 {table.name} ID가 포함되어 있습니다. 전체 작업을 취소했습니다.")
                if any(row["owner_id"] not in (None, account_id) for row in rows):
                    raise click.ClickException("다른 계정에 귀속된 자료는 변경할 수 없습니다. 전체 작업을 취소했습니다.")
                targets.extend((table, row) for row in rows)
            claimed_reports = {row["id"] for table, row in targets if table is reports}
            for table, row in targets:
                if table is appointments and row["report_id"] is not None and row["report_id"] not in claimed_reports:
                    allowed = connection.scalar(select(reports.c.id).where(
                        reports.c.id == row["report_id"], readable_condition(reports, "tci", account_id)))
                    if allowed is None:
                        raise click.ClickException("일정의 연결 검사에도 이 계정의 소유권 또는 공유 권한이 필요합니다.")
            pending = [(table, row) for table, row in targets if row["owner_id"] is None]
            if apply_changes:
                for table, row in pending:
                    result = connection.execute(table.update().where(table.c.id == row["id"], table.c.owner_id.is_(None))
                                                .values(owner_id=account_id))
                    if result.rowcount != 1:
                        raise click.ClickException("점검 중 소유권이 변경되어 전체 작업을 취소했습니다.")
            click.echo(("귀속 완료" if apply_changes else "점검 전용 · 실제 변경 없음") +
                       f" · 대상 {len(targets)}건 · 미귀속 {len(pending)}건 · 기존 본문/점수 보존")

    @app.cli.command("upgrade-selection")
    def upgrade_selection_command():
        """해석 연결 컬럼만 추가한다. 기존 자료·보고서 행은 변경하지 않는다."""
        with get_engine().begin() as connection:
            columns = {c['name'] for c in inspect(connection).get_columns('interpretations')}
            if 'selection' in columns:
                click.echo("selection 컬럼이 이미 있습니다. 변경 없음")
                return
            kind = 'JSONB' if connection.dialect.name == 'postgresql' else 'JSON'
            connection.execute(text(f'ALTER TABLE interpretations ADD COLUMN selection {kind}'))
        click.echo("selection 컬럼 추가 완료 · 기존 행 유지")

    @app.cli.command("upgrade-composition")
    def upgrade_composition_command():
        """기존 보고서에 nullable JSON 컬럼만 추가한다. 행은 변경하지 않는다."""
        with get_engine().begin() as connection:
            columns = {c['name'] for c in inspect(connection).get_columns('reports')}
            if 'composition' in columns:
                click.echo("composition 컬럼이 이미 있습니다. 변경 없음")
                return
            kind = 'JSONB' if connection.dialect.name == 'postgresql' else 'JSON'
            connection.execute(text(f'ALTER TABLE reports ADD COLUMN composition {kind}'))
        click.echo("composition 컬럼 추가 완료 · 기존 행 유지")

    @app.cli.command("init-db")
    def init_db_command():
        """없는 테이블을 생성한다. 기존 데이터는 유지한다."""
        metadata.create_all(get_engine())
        click.echo("DB 테이블 준비 완료")

    @app.cli.command("create-user")
    @click.option("--username", prompt="로그인 아이디", default="admin")
    @click.password_option(prompt="로그인 비밀번호", confirmation_prompt=True)
    def create_user_command(username, password):
        """로그인 계정을 생성한다. 기존 계정은 덮어쓰지 않는다."""
        username = username.strip()
        if not username or len(username) > 80 or not password:
            raise click.ClickException("아이디와 비밀번호를 확인해 주세요.")
        metadata.create_all(get_engine())
        with get_engine().begin() as connection:
            if connection.execute(select(users.c.id).where(users.c.username == username)).first():
                raise click.ClickException("이미 있는 아이디입니다.")
            connection.execute(users.insert().values(
                username=username, password_hash=generate_password_hash(password),
            ))
        click.echo(f"{username} 계정 생성 완료")
