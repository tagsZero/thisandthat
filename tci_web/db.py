from datetime import datetime, timezone

import click
from flask import current_app
from sqlalchemy import (
    JSON, Boolean, Column, Date, DateTime, ForeignKey, Integer, MetaData,
    String, Table, Text, Time, select, inspect, text,
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
)
reports = Table(
    "reports", metadata,
    Column("id", Integer, primary_key=True),
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
    Column("day", Date, nullable=False),
    Column("time", Time, nullable=False),
    Column("title", String(120), nullable=False),
    Column("note", Text, nullable=False, default=""),
    Column("report_id", ForeignKey("reports.id"), nullable=True),
)

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


def init_app(app):
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
