"""
Veritabani baglantisi ve oturum yonetimi.

SQLite kullaniyoruz - tek dosya (flightrotate.db), ayri server gerektirmez.
SQLAlchemy ORM ile DB'ye erisiyoruz.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.engine import Engine

# Veritabani dosyasinin yolu. backend/ klasorunde flightrotate.db olusacak.
DATABASE_URL = "sqlite:///./flightrotate.db"

# Engine: SQLAlchemy'nin veritabaniyla konustugu ana nesne.
# check_same_thread=False -> FastAPI'nin farkli thread'lerden erisimine izin verir.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,  # True yaparsan calisan tum SQL sorgularini terminalde gosterir
)


# SQLite performans ve dogruluk ayarlari.
# Her yeni baglantida bu PRAGMA komutlari calisir.
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")      # Foreign key kisitlarini zorunlu kil
    cursor.execute("PRAGMA journal_mode=WAL")     # Daha iyi okuma/yazma performansi
    cursor.execute("PRAGMA synchronous=NORMAL")   # Hizli yazma
    cursor.close()


# SessionLocal: Her veritabani islemi icin bir oturum (session) uretir.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base: Tum tablo modelleri bu siniftan turetilir.
Base = declarative_base()


def get_db():
    """
    FastAPI endpoint'lerinde kullanilacak veritabani oturumu saglayicisi.
    Islem bitince oturumu otomatik kapatir.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema():
    """
    Lightweight, idempotent migrations for the SQLite database (the project has
    no Alembic). Adds columns introduced after a database was first created, so
    an existing flightrotate.db keeps working without being recreated. Safe to
    call on every startup: it only acts when a column is missing.
    """
    from datetime import datetime
    from sqlalchemy import text

    def _columns(conn, table):
        return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}

    with engine.connect() as conn:
        run_cols = _columns(conn, "optimization_runs")
        if run_cols and "status" not in run_cols:
            conn.execute(text(
                "ALTER TABLE optimization_runs "
                "ADD COLUMN status VARCHAR(20) DEFAULT 'draft'"
            ))
            conn.commit()

        # --- Multi-plan: a plans table + plan_id on the owned tables ---
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS plans ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " name VARCHAR(80) NOT NULL,"
            " created_at DATETIME,"
            " is_active BOOLEAN NOT NULL DEFAULT 0,"
            " deleted_at DATETIME)"
        ))
        # Flights and runs are per-plan; the fleet (aircraft) stays global.
        for table in ("flights", "optimization_runs"):
            cols = _columns(conn, table)
            if cols and "plan_id" not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN plan_id INTEGER"))
        conn.commit()

        # Backfill: if there is no plan yet, create a default active plan and
        # adopt all existing (orphan) flights/runs into it.
        plan_count = conn.execute(text("SELECT COUNT(*) FROM plans")).scalar()
        if plan_count == 0:
            conn.execute(
                text("INSERT INTO plans (name, created_at, is_active) "
                     "VALUES ('Plan 1', :now, 1)"),
                {"now": datetime.utcnow().isoformat()},
            )
            pid = conn.execute(
                text("SELECT id FROM plans WHERE is_active = 1")
            ).scalar()
            for table in ("flights", "optimization_runs"):
                conn.execute(
                    text(f"UPDATE {table} SET plan_id = :pid WHERE plan_id IS NULL"),
                    {"pid": pid},
                )
            conn.commit()


def init_db():
    """
    Tum tablolari olusturur (eger yoksa).
    models.py'deki tum modelleri Base'e kaydeder, sonra create_all cagirir.
    """
    # models'i import etmek, tablolarin Base'e kaydolmasini saglar
    from persistence import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    print("Veritabani tablolari olusturuldu.")