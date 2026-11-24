import re

from app import db
from app.services.llm import tanya_json
from app.worker import app
from .base import aman, ambil_prompt

KODE = "penulis"
LAYAK = {"didukung_2_sumber", "didukung_1_sumber"}


@app.task(name="app.karyawan.khotib_penulis.jalankan", bind=True, max_retries=3)
@aman(KODE)
def jalankan(self, isu_id: int):
    isu = db.query("SELECT * FROM isu WHERE id=:i", i=isu_id)[0]
    cek = db.query("SELECT * FROM fakta_check WHERE isu_id=:i ORDER BY id DESC LIMIT 1", i=isu_id)[0]
    gaya = db.query("SELECT nilai FROM pengaturan WHERE kunci='gaya_bahasa'")
    gaya = gaya[0]["nilai"] if gaya else ""

    # Hanya fakta yang didukung sumber yang boleh dipakai penulis
    layak = [f"- {p['fakta']} (sumber: {isu['sumber']})"
             for p in (cek["detail"] or {}).get("per_fakta", []) if p.get("status") in LAYAK]
    if not layak:
        raise ValueError("Tidak ada fakta layak pakai untuk ditulis")

    pesan = (f"JUDUL ISU: {isu['judul']}\nLABEL FAKTA: {cek['label']}\n"
             f"GAYA TAMBAHAN DARI OWNER: {gaya}\n"
             f"CATATAN OWNER: {isu['catatan_owner'] or '-'}\n\nFAKTA LAYAK:\n" + "\n".join(layak))
    hasil = tanya_json(ambil_prompt(KODE), pesan)

    isi = (hasil.get("isi") or "").strip()
    hook = (hasil.get("hook") or "").strip()
    kata = len(re.findall(r"\w+", isi))
    if not hook or not isi.startswith(hook[:20]):
        raise ValueError("Naskah tidak diawali hook")
    if not 70 <= kata <= 125:  # ~30-45 detik; kalau meleset, retry otomatis
        raise ValueError(f"Panjang naskah {kata} kata, di luar 70-125")

    versi = db.query("SELECT COALESCE(MAX(versi),0)+1 AS v FROM naskah WHERE isu_id=:i", i=isu_id)[0]["v"]
    db.execute(
        "INSERT INTO naskah (isu_id, versi, hook, isi, durasi_est, catatan_akurasi) "
        "VALUES (:i,:v,:h,:s,:d,:c)",
        i=isu_id, v=versi, h=hook, s=isi, d=round(kata / 2.8), c=hasil.get("catatan_akurasi", ""))
    db.execute("UPDATE isu SET tahap='ditulis' WHERE id=:i", i=isu_id)
    return {"versi": versi, "kata": kata, "durasi_est": round(kata / 2.8)}