from datetime import datetime
from zoneinfo import ZoneInfo
import holidays
from sqlalchemy import create_engine, text
from .config import settings

WIB = ZoneInfo("Asia/Jakarta")
engine = create_engine(settings.DATABASE_URL)

def boleh_kerja(sekarang: datetime | None = None) -> tuple[bool, str]:
    """Cek: bukan Minggu, bukan tanggal merah, jam 08:00-15:00 WIB."""
    n = sekarang or datetime.now(WIB)

    if n.weekday() == settings.HARI_LIBUR:
        return False, "Hari Minggu: libur"

    kalender = holidays.Indonesia(years=n.year)
    if n.date() in kalender:
        return False, f"Tanggal merah: {kalender.get(n.date())}"

    with engine.connect() as c:
        r = c.execute(text("SELECT keterangan FROM libur_tambahan WHERE tanggal=:t"),
                      {"t": n.date()}).fetchone()
    if r:
        return False, f"Libur tambahan: {r[0]}"

    if not (settings.JAM_MULAI <= n.hour < settings.JAM_SELESAI):
        return False, "Di luar jam kerja (08:00-15:00 WIB)"

    return True, "OK"