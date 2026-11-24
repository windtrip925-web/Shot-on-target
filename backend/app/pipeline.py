
import os
import redis

from datetime import datetime
from zoneinfo import ZoneInfo

from .worker import app
from .config import settings
from . import db
from .karyawan_kode.base import PETA_TAHAP


def jam_kerja():
    if os.environ.get("MODE_UJI", "").lower() == "true":
        return True

    sekarang = datetime.now(ZoneInfo("Asia/Jakarta"))

    return (
        sekarang.weekday() != 6
        and 8 <= sekarang.hour < 15
    )


@app.task(name="app.pipeline.tick")
def tick():
    if not jam_kerja():
        return "di luar jam kerja"

    r = redis.Redis.from_url(settings.REDIS_URL)

    terkirim = []

    for tahap, nama_task in PETA_TAHAP.items():
        rows = db.query(
            """
            SELECT id
            FROM isu
            WHERE tahap = :t
            ORDER BY id
            LIMIT 5
            """,
            t=tahap
        )

        for row in rows:
            isu_id = row["id"]

        # Khotib hanya menerima naskah jika Noval menemukan
        # sedikitnya satu fakta yang didukung sumber.
        if tahap == "dicek":
            hasil_cek = db.query(
                "SELECT detail FROM fakta_check "
                "WHERE isu_id=:i ORDER BY id DESC LIMIT 1",
                i=isu_id,
            )

            if not hasil_cek:
                print(f"[PIPELINE] Isu {isu_id}: menunggu hasil Noval")
                continue

            detail = hasil_cek[0]["detail"] or {}
            per_fakta = (
                detail.get("per_fakta", [])
                if isinstance(detail, dict) else []
            )

            fakta_layak = any(
                isinstance(f, dict)
                and f.get("status") in {
                    "didukung_1_sumber",
                    "didukung_2_sumber",
                }
                for f in per_fakta
            )

            if not fakta_layak:
                print(
                    f"[PIPELINE] Isu {isu_id}: "
                    "belum ada fakta layak untuk Khotib"
                )
                continue

            kunci = f"kunci:{tahap}:{isu_id}"

            if not r.set(kunci, 1, nx=True, ex=900):
                continue

            try:
                app.send_task(
                    nama_task,
                    kwargs={"isu_id": isu_id}
                )
                terkirim.append(f"{tahap}#{isu_id}")

            except Exception:
                r.delete(kunci)
                raise

            break

    print("[PIPELINE] Tugas dikirim:", terkirim)

    return terkirim
