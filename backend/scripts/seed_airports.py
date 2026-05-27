"""
OpenFlights airports.dat dosyasini parse eder, Turkiye havalimanlarini
filtreler ve airports tablosuna yukler.

Calistirma (backend klasorunden):
    python scripts/seed_airports.py
"""

import sys
from pathlib import Path

# backend/ klasorunu import yoluna ekle
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import pandas as pd
from persistence.database import SessionLocal
from persistence.models import Airport

# airports.dat dosyasinin yolu
AIRPORTS_DAT = BACKEND_DIR / "persistence" / "airports.dat"

# OpenFlights airports.dat kolon isimleri (dosyada baslik satiri yok)
COLUMNS = [
    "openflights_id", "name", "city", "country", "iata", "icao",
    "latitude", "longitude", "altitude", "timezone_offset", "dst",
    "tz_database", "type", "source",
]

# Operasyonel havalimanlari: sentetik ureteci bu havalimanlarina ucus uretir.
# Diger Turkiye havalimanlari haritada gorunur ama operasyona girmez.
OPERATIONAL_IATA = {
    "IST", "SAW", "ESB", "ADB", "AYT", "DLM", "BJV", "TZX",
    "GZT", "VAN", "ASR", "KYA", "DIY", "ERZ", "SZF", "NAV",
    "TEQ", "EZS", "MLX", "GZP",
}


def seed_airports():
    print("airports.dat okunuyor...")

    # Dosyayi oku. \N -> eksik deger olarak yorumlanir.
    df = pd.read_csv(
        AIRPORTS_DAT,
        header=None,
        names=COLUMNS,
        na_values=["\\N"],
        keep_default_na=True,
    )

    # Turkiye havalimanlarini, IATA kodu olanlari ve gercek havalimani olanlari filtrele
    turkey = df[
        (df["country"] == "Turkey")
        & (df["iata"].notna())
        & (df["type"] == "airport")
    ].copy()

    print(f"Turkiye'de {len(turkey)} havalimani bulundu.")

    db = SessionLocal()
    added = 0
    skipped = 0

    try:
        for _, row in turkey.iterrows():
            iata = str(row["iata"]).strip()

            # Bu havalimani zaten tabloda var mi? (tekrar calistirmaya karsi koruma)
            existing = db.query(Airport).filter(Airport.iata_code == iata).first()
            if existing:
                skipped += 1
                continue

            airport = Airport(
                iata_code=iata,
                icao_code=str(row["icao"]).strip() if pd.notna(row["icao"]) else None,
                name=str(row["name"]).strip(),
                city=str(row["city"]).strip() if pd.notna(row["city"]) else None,
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
                timezone=str(row["tz_database"]).strip() if pd.notna(row["tz_database"]) else "Europe/Istanbul",
                min_turnaround_min=45,
                is_operational=(iata in OPERATIONAL_IATA),
            )
            db.add(airport)
            added += 1

        db.commit()
        print(f"\n{added} havalimani eklendi, {skipped} zaten vardi (atlandi).")

        # Operasyonel havalimanlarini listele - dogrulama
        operational = db.query(Airport).filter(Airport.is_operational == True).all()
        print(f"\nOperasyonel havalimanlari ({len(operational)} adet):")
        for a in sorted(operational, key=lambda x: x.iata_code):
            print(f"  {a.iata_code} - {a.name}")

    except Exception as e:
        db.rollback()
        print(f"HATA: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_airports()