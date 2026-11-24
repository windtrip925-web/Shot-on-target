from celery import Celery
from .config import settings

celery_app = Celery(
    "studio",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.karyawan_kode.base",
        "app.karyawan_kode.agim_perekap",
        "app.karyawan_kode.noval_factcheck",
        "app.karyawan_kode.khotib_penulis",
        "app.karyawan_kode.dede_sutradara",
        "app.karyawan_kode.marno_suara",
        "app.karyawan_kode.kadir_editor",
        "app.karyawan_kode.marwan_perintah",
        "app.karyawan_kode.marwan_pemburu",
        "app.karyawan_kode.syair_publisher",
        "app.pipeline",
    ],
)

celery_app.conf.timezone = "Asia/Jakarta"
app = celery_app

from celery.schedules import crontab

celery_app.conf.beat_schedule = {
    "pipeline-tick": {
        "task": "app.pipeline.tick",
        "schedule": crontab(
            minute="*/10",
            hour="8-14",
            day_of_week="mon-sat",
        ),
    },
    "marwan-pemburu-berita": {
        "task": "app.karyawan.marwan_pemburu.jalankan",
        "schedule": crontab(
            minute="*/30",
            hour="8-14",
            day_of_week="mon-sat",
        ),
    },
}


# Registrasi karyawan tambahan Shot on Target
from .karyawan_kode import marwan_pemburu, syair_publisher
