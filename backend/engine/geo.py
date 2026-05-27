"""
Cografi hesaplamalar.

haversine: iki koordinat arasindaki buyuk cember mesafesini (km) hesaplar.
Bu fonksiyon hem sentetik ucus uretecinde (ucus suresi) hem de
Cost Model'de (yakit hesabi) kullanilir.
"""

from math import radians, sin, cos, sqrt, atan2

# Dunya'nin ortalama yaricapi (km)
EARTH_RADIUS_KM = 6371.0


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Iki nokta arasindaki buyuk cember (great-circle) mesafesini km olarak dondurur.

    Parametreler:
        lat1, lon1: birinci noktanin enlem/boylami (derece)
        lat2, lon2: ikinci noktanin enlem/boylami (derece)

    Donen deger:
        Mesafe (kilometre)
    """
    # Dereceleri radyana cevir
    phi1, phi2 = radians(lat1), radians(lat2)
    delta_phi = radians(lat2 - lat1)
    delta_lambda = radians(lon2 - lon1)

    # Haversine formulu
    a = (
        sin(delta_phi / 2) ** 2
        + cos(phi1) * cos(phi2) * sin(delta_lambda / 2) ** 2
    )
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return EARTH_RADIUS_KM * c


def estimate_flight_duration_minutes(distance_km: float) -> int:
    """
    Mesafeye gore yaklasik ucus suresini dakika olarak tahmin eder.

    Basit model: B737-800 ortalama yer hizi ~750 km/saat (cruise).
    Buna ek olarak kalkis/inis/manevra icin sabit 30 dakika eklenir.

    Parametreler:
        distance_km: ucus mesafesi (km)

    Donen deger:
        Tahmini ucus suresi (dakika, tam sayi)
    """
    CRUISE_SPEED_KMH = 750.0
    FIXED_OVERHEAD_MIN = 30  # kalkis + tirmanis + inis manevra payi

    cruise_minutes = (distance_km / CRUISE_SPEED_KMH) * 60
    total = cruise_minutes + FIXED_OVERHEAD_MIN

    return int(round(total))