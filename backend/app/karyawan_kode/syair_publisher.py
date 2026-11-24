import os
from pathlib import Path

from app import db
from app.worker import app
from .base import log

KODE = "publisher"
FOLDER_HASIL = Path("/media/hasil")


def _lapor(pesan, isu_id=None, level="info"):
    log(KODE, pesan, isu_id=isu_id, level=level)


@app.task(
    name="app.karyawan.syair_publisher.jalankan",
    bind=True,
    max_retries=2,
)
def jalankan(self, isu_id):
    rows = db.query(
        "SELECT id, judul, tahap FROM isu WHERE id=:i",
        i=isu_id,
    )
    if not rows:
        raise ValueError(f"Isu {isu_id} tidak ditemukan.")

    isu = rows[0]

    if isu["tahap"] != "disetujui":
        pesan = f"Publikasi ditahan: isu {isu_id} belum disetujui Owner."
        _lapor(pesan, isu_id, "warn")
        return {"status": "menunggu_persetujuan", "isu_id": isu_id}

    media = db.query(
        """
        SELECT path FROM media
        WHERE isu_id=:i AND jenis='video'
        ORDER BY id DESC
        LIMIT 1
        """,
        i=isu_id,
    )
    if not media:
        _lapor(
            f"Publikasi ditahan: catatan video isu {isu_id} tidak ada.",
            isu_id,
            "warn",
        )
        return {"status": "menunggu_video", "isu_id": isu_id}

    video = Path(media[0]["path"])
    folder_resmi = (FOLDER_HASIL / str(isu_id)).resolve()

    # Pastikan file berasal dari folder hasil isu yang bersangkutan.
    if (
        video.suffix.lower() != ".mp4"
        or video.resolve().parent != folder_resmi
        or not video.is_file()
        or video.stat().st_size == 0
    ):
        _lapor(
            f"Publikasi ditahan: file video isu {isu_id} tidak valid.",
            isu_id,
            "warn",
        )
        return {"status": "video_tidak_valid", "isu_id": isu_id}

    konfigurasi = {
        "youtube": bool(os.getenv("YOUTUBE_CLIENT_ID")),
        "tiktok": bool(os.getenv("TIKTOK_ACCESS_TOKEN")),
        "meta": bool(os.getenv("META_ACCESS_TOKEN")),
    }

    pesan = (
        f"Video isu {isu_id} lolos pemeriksaan persetujuan dan file. "
        "Menunggu konektor resmi platform untuk publikasi."
    )
    _lapor(pesan, isu_id)

    return {
        "status": "menunggu_integrasi_platform",
        "isu_id": isu_id,
        "video": str(video),
        "platform_terkonfigurasi": konfigurasi,
    }
