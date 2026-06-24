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
    from sqlalchemy import text

    with engine.connect() as conn:
        existing = {
            row[1]  # PRAGMA table_info columns: (cid, name, type, ...)
            for row in conn.execute(text("PRAGMA table_info(optimization_runs)"))
        }
        if existing and "status" not in existing:
            conn.execute(text(
                "ALTER TABLE optimization_runs "
                "ADD COLUMN status VARCHAR(20) DEFAULT 'draft'"
            ))
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