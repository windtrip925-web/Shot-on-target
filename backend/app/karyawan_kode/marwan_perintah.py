import re
import urllib.parse

import httpx

from app import db
from app.services.llm import tanya_json
from app.worker import app
from .base import aman, log

KODE = "pemburu"
HEADER = {"User-Agent": "ShotOnTarget/1.0 (studio konten)"}
WIKI = "https://en.wikipedia.org/w/api.php"

PROMPT = """Kamu Marwan, Pemburu Isu studio "Shot on Target" (reels sepak bola).
Owner memberi perintah. Usulkan kandidat topik yang sesuai perintah.
ATURAN KERAS:
- Hanya peristiwa yang benar-benar terjadi dan terkenal. Dilarang mengarang. Kalau ragu, jangan masukkan.
- "judul": bahasa Indonesia, singkat.
- "kata_kunci": judul artikel Wikipedia bahasa Inggris yang paling mungkin ada
  (contoh: "2002 UEFA Champions League final").
Format: [{"judul": "...", "kata_kunci": "...", "skor": 0-100}]"""


def _cari_wiki(kata_kunci: str):
    r = httpx.get(WIKI, timeout=20, headers=HEADER, params={
        "action": "query", "list": "search", "srsearch": kata_kunci,
        "srlimit": 1, "format": "json"})
    r.raise_for_status()
    hit = r.json().get("query", {}).get("search", [])
    if not hit:
        return None
    return hit[0]["title"], re.sub(r"<[^>]+>", "", hit[0].get("snippet", ""))


@app.task(name="app.karyawan.marwan_perintah.kerjakan", bind=True, max_retries=2)
@aman(KODE)
def kerjakan(self, *, perintah_id: int):
    p = db.query("SELECT * FROM perintah WHERE id=:i", i=perintah_id)[0]
    db.execute("UPDATE perintah SET status='berjalan' WHERE id=:i", i=perintah_id)
    try:
        kandidat = tanya_json(
            PROMPT, f"PERINTAH OWNER: {p['teks']}\nJumlah dibutuhkan: {p['jumlah']}\n"
                    f"Beri {p['jumlah'] + 5} kandidat, urut dari yang paling kuat.")
        tersimpan = 0
        for c in kandidat:
            if tersimpan >= p["jumlah"]:
                break
            try:
                hit = _cari_wiki(c["kata_kunci"])
            except Exception as e:
                log(KODE, f"Wikipedia gagal untuk '{c['kata_kunci']}': {e}", level="warn")
                continue
            if not hit:
                log(KODE, f"Tidak ada sumber untuk '{c['judul']}', dilewati", level="warn")
                continue
            judul_wiki, snippet = hit
            url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(judul_wiki.replace(" ", "_"))
            tersimpan += db.execute(
                "INSERT INTO isu (judul, url_sumber, sumber, skor_viral, cuplikan, perintah_id) "
                "VALUES (:j,:u,'Wikipedia',:v,:c,:p) ON CONFLICT (url_sumber) DO NOTHING",
                j=c["judul"], u=url, v=int(c.get("skor", 50)), c=snippet, p=perintah_id)
        status = "selesai" if tersimpan else "gagal"
        db.execute("UPDATE perintah SET status=:s, catatan=:c WHERE id=:i", s=status,
                   c=f"{tersimpan} dari {p['jumlah']} topik berhasil dicarikan sumber", i=perintah_id)
        return {"topik": tersimpan}
    except Exception:
        if self.request.retries >= self.max_retries:
            db.execute("UPDATE perintah SET status='gagal' WHERE id=:i", i=perintah_id)
        raise