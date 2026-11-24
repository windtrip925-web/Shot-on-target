import os
import re
import html
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import httpx

from app import db
from app.worker import app
from .base import log

KODE = "pemburu"
HEADER = {"User-Agent": "ShotOnTarget/2.0"}
BATAS_BERITA = 30


def _teks(value):
    value = html.unescape(value or "")
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _feeds():
    raw = os.getenv("RSS_FEEDS", "")
    return [x.strip() for x in raw.split(",") if x.strip()]


def _ambil_feed(url):
    response = httpx.get(
        url,
        headers=HEADER,
        timeout=25,
        follow_redirects=True,
    )
    response.raise_for_status()

    root = ET.fromstring(response.content)
    hasil = []

    for node in root.iter():
        nama = node.tag.split("}")[-1].lower()
        if nama not in {"item", "entry"}:
            continue

        data = {}
        for child in node:
            k = child.tag.split("}")[-1].lower()
            if k == "link":
                data[k] = child.attrib.get("href") or child.text or ""
            else:
                data[k] = "".join(child.itertext())

        judul = _teks(data.get("title"))
        tautan = (data.get("link") or "").strip()
        ringkasan = _teks(
            data.get("description")
            or data.get("summary")
            or data.get("content")
        )

        if judul and tautan.startswith(("http://", "https://")):
            hasil.append({
                "judul": judul[:500],
                "url": tautan,
                "cuplikan": ringkasan[:5000],
            })

    return hasil


def _simpan(item):
    ada = db.query(
        "SELECT id FROM isu WHERE url_sumber=:u LIMIT 1",
        u=item["url"],
    )
    if ada:
        return False

    host = urlparse(item["url"]).netloc.lower()
    sumber = host.removeprefix("www.") or "RSS"

    db.execute(
        """
        INSERT INTO isu
            (judul, url_sumber, sumber, tanggal_terbit,
             skor_viral, tahap, cuplikan)
        VALUES
            (:j, :u, :s, NOW(), 0, 'baru', :c)
        """,
        j=item["judul"],
        u=item["url"],
        s=sumber[:200],
        c=item["cuplikan"],
    )
    return True


@app.task(
    name="app.karyawan.marwan_pemburu.jalankan",
    bind=True,
    max_retries=2,
)
def jalankan(self):
    daftar_feed = _feeds()

    if not daftar_feed:
        pesan = "RSS_FEEDS belum diisi. Marwan menunggu konfigurasi sumber."
        log(KODE, pesan)
        return {"status": "menunggu_sumber", "jumlah": 0}

    baru = 0
    gagal = []

    for url in daftar_feed:
        try:
            berita = _ambil_feed(url)
            for item in berita:
                if baru >= BATAS_BERITA:
                    break
                if _simpan(item):
                    baru += 1
        except Exception as exc:
            gagal.append(f"{url}: {str(exc)[:180]}")

    pesan = f"Marwan menemukan {baru} berita baru."
    log(KODE, pesan)

    return {
        "status": "selesai",
        "berita_baru": baru,
        "feed_gagal": gagal,
    }
