import json
import re

from app import db
from app.services.llm import tanya_json
from app.worker import app
from .base import aman, ambil_prompt, log

KODE = "factcheck"
LABEL = {"Terverifikasi", "Perlu Dicek", "Disengketakan"}


def _kata(s: str) -> set[str]:
    return {w for w in re.findall(r"\w+", (s or "").lower()) if len(w) > 3}


def _pembanding(isu: dict) -> list[dict]:
    """Cari berita mirip dari MEDIA LAIN dalam 7 hari terakhir."""
    a = _kata(isu["judul"])
    baris = db.query(
        "SELECT judul, sumber, cuplikan FROM isu WHERE id<>:i "
        "AND sumber IS DISTINCT FROM :s AND created_at > now() - interval '7 days' "
        "ORDER BY id DESC LIMIT 300", i=isu["id"], s=isu["sumber"])
    cocok = []
    for r in baris:
        b = _kata(r["judul"])
        if a and b and len(a & b) / len(a | b) >= 0.25:
            cocok.append((len(a & b) / len(a | b), r))
    cocok.sort(key=lambda x: -x[0])
    return [r for _, r in cocok[:5]]


@app.task(name="app.karyawan.noval_factcheck.jalankan", bind=True, max_retries=3)
@aman(KODE)
def jalankan(self, isu_id: int):
    isu = db.query("SELECT * FROM isu WHERE id=:i", i=isu_id)[0]
    rekap = db.query("SELECT * FROM rekap WHERE isu_id=:i ORDER BY id DESC LIMIT 1", i=isu_id)[0]
    banding = _pembanding(isu)
    teks_banding = "\n".join(f"- [{b['sumber']}] {b['judul']} | {(b['cuplikan'] or '')[:250]}"
                             for b in banding) or "(tidak ada berita pembanding)"

    hasil = tanya_json(
        ambil_prompt(KODE),
        f"FAKTA KUNCI:\n{json.dumps(rekap['fakta_kunci'], ensure_ascii=False)}\n\n"
        f"TEKS SUMBER ({isu['sumber']}):\n{rekap['teks_sumber']}\n\n"
        f"BERITA PEMBANDING:\n{teks_banding}")

    label = hasil.get("label") if hasil.get("label") in LABEL else "Perlu Dicek"
    per_fakta = hasil.get("per_fakta", [])
    status = [p.get("status") for p in per_fakta]
    alasan = hasil.get("alasan", "")

    # ---- ATURAN KUNCI (kode yang memutuskan, bukan AI) ----
    if "bertentangan" in status:
        label = "Disengketakan"
    elif label == "Terverifikasi":
        if not per_fakta or any(s != "didukung_2_sumber" for s in status):
            label = "Perlu Dicek"
            alasan += " [Diturunkan: tidak semua fakta punya 2 sumber]"
        elif rekap["dasar"] == "cuplikan_saja":
            label = "Perlu Dicek"
            alasan += " [Diturunkan: artikel penuh tidak terbaca, hanya cuplikan]"

    db.execute("DELETE FROM fakta_check WHERE isu_id=:i", i=isu_id)
    db.execute(
        "INSERT INTO fakta_check (isu_id, label, alasan, detail) "
        "VALUES (:i,:l,:a, CAST(:d AS JSONB))",
        i=isu_id, l=label, a=alasan,
        d=json.dumps({"per_fakta": per_fakta, "pembanding": [b["sumber"] for b in banding]},
                     ensure_ascii=False))

    if label == "Disengketakan":
        db.execute("UPDATE isu SET tahap='berhenti_disengketakan' WHERE id=:i", i=isu_id)
        log(KODE, f"BERHENTI di antrean owner: {alasan}", isu_id=isu_id, level="warn")
    else:
        db.execute("UPDATE isu SET tahap='dicek' WHERE id=:i", i=isu_id)
    return {"label": label}