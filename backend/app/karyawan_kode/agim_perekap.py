
import html
import re
import json

import httpx

from app import db
from app.services.llm import tanya_json
from app.worker import app
from .base import aman, ambil_prompt

KODE = "perekap"
HEADER = {"User-Agent": "ShotOnTarget/1.0"}


def _ambil_teks(url: str, cadangan: str):
    try:
        r = httpx.get(
            url,
            timeout=20,
            follow_redirects=True,
            headers=HEADER
        )
        r.raise_for_status()

        h = re.sub(
            r"(?is)<(script|style|nav|footer|header|aside)[^>]*>.*?</\1>",
            " ",
            r.text
        )
        paragraf = re.findall(r"(?is)<p[^>]*>(.*?)</p>", h)
        teks = " ".join(
            re.sub(r"<[^>]+>", "", p) for p in paragraf
        )
        teks = re.sub(r"\s+", " ", html.unescape(teks)).strip()

        if len(teks) > 400:
            return teks[:6000], "artikel_penuh"

    except Exception:
        pass

    return cadangan or "", "cuplikan_saja"


@app.task(name="app.karyawan.agim_perekap.jalankan", bind=True, max_retries=3)
@aman(KODE)
def jalankan(self, isu_id: int):
    rows = db.query(
        "SELECT * FROM isu WHERE id=:i",
        i=isu_id
    )

    if not rows:
        raise ValueError(f"Isu {isu_id} tidak ditemukan")

    isu = rows[0]

    teks, dasar = _ambil_teks(
        isu["url_sumber"],
        isu["cuplikan"] if "cuplikan" in isu else ""
    )

    if len(teks) < 30:
        raise ValueError("Teks sumber terlalu pendek untuk direkap")

    hasil = tanya_json(
        ambil_prompt(KODE),
        f"JUDUL: {isu['judul']}\n"
        f"SUMBER: {isu['sumber']}\n"
        f"TANGGAL TERBIT: {isu['tanggal_terbit']}\n\n"
        f"TEKS SUMBER:\n{teks}"
    )

    sumber = f"{isu['sumber']} ({isu['url_sumber']})"

    tgl = isu["tanggal_terbit"]
    tgl_terbit = tgl.date().isoformat() if tgl else None

    fakta = [
        {
            "fakta": f["fakta"],
            "sumber": sumber,
            "tanggal": f.get("tanggal") or tgl_terbit
        }
        for f in hasil.get("fakta", [])
        if f.get("fakta")
    ]

    if not fakta:
        raise ValueError("AI tidak menghasilkan fakta yang dapat dicatat")

    ringkasan = hasil.get("ringkasan", "")

    if hasil.get("tidak_jelas"):
        ringkasan += (
            "\n\nBELUM TERVERIFIKASI: "
            + "; ".join(hasil["tidak_jelas"])
        )

    db.execute(
        "DELETE FROM rekap WHERE isu_id=:i",
        i=isu_id
    )

    db.execute(
        """
        INSERT INTO rekap (isu_id, fakta_kunci, ringkasan)
        VALUES (:i, CAST(:f AS JSONB), :r)
        """,
        i=isu_id,
        f=json.dumps(fakta, ensure_ascii=False),
        r=ringkasan
    )

    db.execute(
        "UPDATE isu SET tahap='direkap' WHERE id=:i",
        i=isu_id
    )

    return {
        "isu_id": isu_id,
        "fakta": len(fakta),
        "dasar": dasar,
        "status": "direkap"
    }
