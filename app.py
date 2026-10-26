import os
import secrets
from pathlib import Path

from dotenv import load_dotenv, set_key
from flask import Flask
from sqlalchemy import URL, create_engine


def create_app(test_config=None):
    env_path = Path(__file__).with_name(".env")
    load_dotenv(env_path, encoding="utf-8-sig")

    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"]:
        app.config["SECRET_KEY"] = secrets.token_hex(32)
        set_key(str(env_path), "SECRET_KEY", app.config["SECRET_KEY"])

    database_url = app.config.get("DATABASE_URL") or URL.create(
        drivername="postgresql+psycopg",
        username=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        database=os.environ["DB_NAME"],
    )
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={} if str(database_url).startswith("sqlite") else {"connect_timeout": 5},
    )
    app.extensions["db_engine"] = engine

    from tci_web import auth, db, views, library, candidates, final_report, pdf_export, type_library

    db.init_app(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(views.bp)
    library.init_app(app)  # 소스·해석 관리와 명시적 초기 자료 등록
    type_library.init_app(app)  # TYPE-01 상세 전사 팩: 기본 읽기 전용, 명시적 적용만 쓰기
    app.register_blueprint(candidates.bp)
    app.register_blueprint(final_report.bp)
    app.register_blueprint(pdf_export.bp)

    from khtp_web import init_app as init_khtp
    init_khtp(app)

    @app.template_filter("local_datetime")
    def local_datetime(value):
        from datetime import timezone
        from zoneinfo import ZoneInfo

        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y.%m.%d %H:%M")

    return app
