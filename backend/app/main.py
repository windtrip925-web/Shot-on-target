import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse

from . import db
from .worker import celery_app

api = FastAPI(title="Shot on Target")

api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def cek_owner(pw):
    benar = os.environ.get("OWNER_PASSWORD", "")
    if not benar or pw != benar:
        raise HTTPException(401, "Password owner salah")


def _kolom(tabel):
    rows = db.query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = :t",
        t=tabel,
    )
    return [x["column_name"] for x in rows]


@api.get("/health")
def health():
    return {"ok": True}


@api.get("/api/beranda")
def beranda(x_owner: str = Header(default="")):
    cek_owner(x_owner)
    per_tahap = db.query(
        "SELECT tahap, COUNT(*) AS jumlah FROM isu GROUP BY tahap"
    )
    return {"per_tahap": per_tahap}


@api.get("/api/isu/{isu_id}")
def lihat_isu(isu_id: int, x_owner: str = Header(default="")):
    cek_owner(x_owner)
    rows = db.query("SELECT * FROM isu WHERE id = :i", i=isu_id)
    if not rows:
        raise HTTPException(404, "Isu tidak ada")
    return rows[0]


@api.get("/api/antrean/disengketakan")
def antrean(x_owner: str = Header(default="")):
    cek_owner(x_owner)
    return db.query(
        "SELECT * FROM isu WHERE tahap = 'berhenti_disengketakan' "
        "ORDER BY id DESC"
    )


@api.post("/api/isu/{isu_id}/putuskan")
def putuskan(
    isu_id: int,
    keputusan: str,
    x_owner: str = Header(default=""),
):
    cek_owner(x_owner)
    peta = {"lanjut": "dicek", "tolak": "ditolak"}
    if keputusan not in peta:
        raise HTTPException(400, "keputusan: lanjut atau tolak")

    n = db.execute(
        "UPDATE isu SET tahap = :t WHERE id = :i",
        t=peta[keputusan],
        i=isu_id,
    )
    return {"diubah": n, "tahap_baru": peta[keputusan]}


@api.get("/api/perintah")
def daftar_perintah(x_owner: str = Header(default="")):
    cek_owner(x_owner)
    return db.query("SELECT * FROM perintah ORDER BY id DESC LIMIT 20")


@api.post("/api/perintah")
def buat_perintah(
    teks: str,
    jumlah: int = 5,
    x_owner: str = Header(default=""),
):
    cek_owner(x_owner)

    if jumlah < 1 or jumlah > 10:
        raise HTTPException(400, "Jumlah harus 1 sampai 10")

    kol = _kolom("perintah")
    tk = next(
        (
            k for k in [
                "teks", "perintah", "isi",
                "kata_kunci", "topik", "judul"
            ] if k in kol
        ),
        None,
    )
    if not tk:
        raise HTTPException(500, "Kolom teks perintah tidak ditemukan")

    data = {tk: teks}
    jk = next(
        (k for k in ["jumlah", "jml", "banyak"] if k in kol),
        None,
    )
    if jk:
        data[jk] = jumlah

    c = ", ".join(data)
    v = ", ".join(f":{k}" for k in data)

    pid = db.query(
        f"INSERT INTO perintah ({c}) VALUES ({v}) RETURNING id",
        **data,
    )[0]["id"]

    celery_app.send_task(
        "app.karyawan.marwan_perintah.kerjakan",
        kwargs={"perintah_id": pid},
    )
    return {"perintah_id": pid, "status": "dikirim ke Marwan"}


@api.get("/api/owner/antrean")
def antrean_owner(x_owner: str = Header(default="")):
    cek_owner(x_owner)

    return db.query("""
        SELECT
            i.id,
            i.judul,
            i.tahap,
            i.catatan_owner,
            MAX(m.path) FILTER (WHERE m.jenis = 'video') AS video_path,
            MAX(m.path) FILTER (WHERE m.jenis = 'thumbnail') AS thumbnail_path,
            MAX(m.path) FILTER (WHERE m.jenis = 'subtitle') AS subtitle_path
        FROM isu i
        LEFT JOIN media m ON m.isu_id = i.id
        WHERE i.tahap = 'menunggu_persetujuan'
        GROUP BY i.id
        ORDER BY i.id DESC
    """)


@api.post("/api/isu/{isu_id}/keputusan")
def keputusan_owner(
    isu_id: int,
    keputusan: str,
    catatan: str = "",
    x_owner: str = Header(default=""),
):
    cek_owner(x_owner)

    peta = {
        "setujui": ("Disetujui", "disetujui"),
        "revisi": ("Revisi", "revisi"),
        "tolak": ("Ditolak", "ditolak"),
    }

    if keputusan not in peta:
        raise HTTPException(
            400,
            "Keputusan harus setujui, revisi, atau tolak",
        )

    isu = db.query(
        "SELECT id, tahap FROM isu WHERE id = :i",
        i=isu_id,
    )

    if not isu:
        raise HTTPException(404, "Isu tidak ditemukan")

    if isu[0]["tahap"] != "menunggu_persetujuan":
        raise HTTPException(
            409,
            "Isu ini tidak sedang menunggu persetujuan",
        )

    label, tahap_baru = peta[keputusan]

    db.execute(
        """
        INSERT INTO persetujuan (isu_id, keputusan, catatan)
        VALUES (:i, :k, :c)
        """,
        i=isu_id,
        k=label,
        c=catatan.strip(),
    )

    db.execute(
        """
        UPDATE isu
        SET tahap = :t, catatan_owner = :c
        WHERE id = :i
        """,
        t=tahap_baru,
        c=catatan.strip(),
        i=isu_id,
    )

    tugas_publikasi_dikirim = False
    pesan_antrean = ""

    if keputusan == "setujui":
        try:
            celery_app.send_task(
                "app.karyawan.syair_publisher.jalankan",
                kwargs={"isu_id": isu_id},
            )
            tugas_publikasi_dikirim = True
        except Exception as exc:
            pesan_antrean = str(exc)[:300]
            print(
                f"[SYAIR] Gagal mengantrekan isu {isu_id}: "
                f"{pesan_antrean}"
            )

    return {
        "ok": True,
        "isu_id": isu_id,
        "keputusan": label,
        "tahap": tahap_baru,
        "tugas_publikasi_dikirim": tugas_publikasi_dikirim,
        "pesan_antrean": pesan_antrean,
    }


@api.get("/media/hasil/{isu_id}/{nama_file}")
def media_hasil(
    isu_id: int,
    nama_file: str,
):

    if Path(nama_file).name != nama_file:
        raise HTTPException(400, "Nama file tidak valid")

    path_db = f"/media/hasil/{isu_id}/{nama_file}"

    rows = db.query(
        """
        SELECT path FROM media
        WHERE isu_id = :i
          AND path = :p
          AND jenis IN ('video', 'thumbnail', 'subtitle')
        """,
        i=isu_id,
        p=path_db,
    )

    if not rows:
        raise HTTPException(404, "Media tidak ditemukan")

    file_path = Path(path_db)

    if not file_path.is_file():
        raise HTTPException(404, "File belum tersedia")

    return FileResponse(str(file_path))


@api.get("/kantor", response_class=HTMLResponse)
def kantor():
    f = Path(__file__).parent / "static" / "kantor.html"
    return f.read_text(encoding="utf-8")


@api.post("/api/pipeline/tick")
def jalankan_tick(x_owner: str = Header(default="")):
    cek_owner(x_owner)
    celery_app.send_task("app.pipeline.tick")
    return {"status": "tick dikirim"}
