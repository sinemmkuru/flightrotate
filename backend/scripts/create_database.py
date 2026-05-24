"""
Veritabanini olusturur. flightrotate.db dosyasini ve 7 tabloyu yaratir.

Calistirma (backend klasorunden):
    python scripts/create_database.py
"""

import sys
from pathlib import Path

# backend/ klasorunu Python'un import yoluna ekle.
# Boylece "from persistence..." importlari calisir.
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from persistence.database import init_db, engine
from sqlalchemy import inspect


def main():
    print("Veritabani olusturuluyor...")
    init_db()

    # Olusan tablolari listele - dogrulama icin
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    print(f"\nToplam {len(tables)} tablo olusturuldu:")
    for table in sorted(tables):
        print(f"  - {table}")


if __name__ == "__main__":
    main()