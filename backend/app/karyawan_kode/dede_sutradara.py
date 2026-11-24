import os
import re
import html
from urllib.parse import urlparse

import httpx
from sqlalchemy import text

from app import db
from app.services.llm import tanya_json
from app.worker import app
from .base import aman, ambil_prompt, log

KODE = "sutradara"
MEDIA = "/media/footage"

API_COMMONS = "https://commons.wikimedia.org/w/api.php"

# Hanya lisensi yang mengizinkan penggunaan ulang secara komersial.
LISENSI_DIIZINKAN = (
    "cc by",
    "cc by-sa",
    "cc0",
    "public domain",
    "pd-old",
    "pd-us",
)

USER_AGENT = "ShotOnTargetStudio/1.0 (automated football video research)"


def _pecah_adegan(isi):
    kalimat = [
        x.strip()
        for x in re.split(r"(?<=[.!?])\s+", isi)
        if x.strip()
    ]
    if not kalimat:
        return []
    n = min(6, len(kalimat))
    return [
        " ".join(kalimat[i * len(kalimat) // n:(i + 1) * len(kalimat) // n])
        for i in range(n)
    ]


def _bersihkan(teks):
    teks = html.unescape(str(teks or ""))
    teks = re.sub(r"<[^>]+>", " ", teks)
    return re.sub(r"\s+", " ", teks).strip()


def _lisensi_boleh(metadata):
    nama = _bersihkan(
        metadata.get("LicenseShortName", {}).get("value", "")
    ).lower()

    istilah = _bersihkan(
        metadata.get("UsageTerms", {}).get("value", "")
    ).lower()

    gabungan = nama + " " + istilah

    if "non-commercial" in gabungan or "noncommercial" in gabungan:
        return False
    if "no derivatives" in gabungan:
        return False

    return any(x in gabungan for x in LISENSI_DIIZINKAN)


def _cari_commons(kata_kunci):
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"filetype:video {kata_kunci}",
        "gsrnamespace": 6,
        "gsrlimit": 10,
        "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata",
    }

    r = httpx.get(
        API_COMMONS,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    r.raise_for_status()

    halaman = r.json().get("query", {}).get("pages", {})
    hasil = []

    for item in halaman.values():
        info = (item.get("imageinfo") or [{}])[0]
        mime = info.get("mime", "")

        if not mime.startswith("video/"):
            continue

        if not _lisensi_boleh(info.get("extmetadata", {})):
            continue

        url = info.get("url")
        if not url:
            continue

        nama = urlparse(url).path.lower()
        ekstensi = os.path.splitext(nama)[1]

        if ekstensi not in (".mp4", ".webm", ".ogv", ".ogg", ".mov"):
            continue

        if info.get("size", 0) > 120 * 1024 * 1024:
            continue

        metadata = info.get("extmetadata", {})
        lisensi = _bersihkan(
            metadata.get("LicenseShortName", {}).get("value", "")
        )
        sumber = info.get("descriptionurl", "")

        hasil.append({
            "url": url,
            "ekstensi": ekstensi,
            "lisensi": lisensi,
            "sumber": sumber,
        })

    return hasil


def _cari_footage(kata_kunci, simpan_ke):
    if not kata_kunci:
        return None

    try:
        kandidat = _cari_commons(kata_kunci)
    except Exception as e:
        log(KODE, f"Pencarian Commons gagal: {e}", level="warning")
        return None

    for video in kandidat:
        tujuan = simpan_ke + video["ekstensi"]
        sementara = tujuan + ".part"

        try:
            os.makedirs(os.path.dirname(tujuan), exist_ok=True)

            total = 0
            with httpx.stream(
                "GET",
                video["url"],
                headers={"User-Agent": USER_AGENT},
                timeout=90,
                follow_redirects=True,
            ) as r:
                r.raise_for_status()

                with open(sementara, "wb") as f:
                    for potongan in r.iter_bytes(1024 * 1024):
                        total += len(potongan)
                        if total > 120 * 1024 * 1024:
                            raise ValueError("Ukuran video melebihi batas 120 MB")
                        f.write(potongan)

            if total < 10000:
                raise ValueError("Berkas video terlalu kecil")

            os.replace(sementara, tujuan)

            catatan = (
                f"{video['lisensi']} | Sumber: {video['sumber']}"
            )

            return tujuan, catatan

        except Exception as e:
            if os.path.exists(sementara):
                os.remove(sementara)
            log(KODE, f"Gagal mengunduh footage: {e}", level="warning")

    return None


@app.task(
    name="app.karyawan.dede_sutradara.jalankan",
    bind=True,
    max_retries=3,
)
@aman(KODE)
def jalankan(self, isu_id):
    naskah = db.query(
        """
        SELECT * FROM naskah
        WHERE isu_id=:i
        ORDER BY versi DESC LIMIT 1
        """,
        i=isu_id,
    )

    if not naskah:
        raise ValueError(f"Naskah isu {isu_id} tidak ditemukan")

    nas = naskah[0]
    bagian = _pecah_adegan(nas["isi"])

    if not bagian:
        raise ValueError("Naskah kosong, tidak bisa membuat adegan")

    daftar = "\n".join(
        f"{i}. {teks}" for i, teks in enumerate(bagian)
    )

    instruksi = (
        "Buat arahan visual untuk setiap adegan sepak bola berikut. "
        "Kata kunci pencarian harus spesifik, utamakan nama pemain, "
        "nama pertandingan, negara, tahun, dan kejadian. "
        "Gunakan kata kunci bahasa Inggris agar pencarian footage lebih luas. "
        "Jangan mengarang sumber atau menyatakan video ditemukan. "
        "Kembalikan JSON berupa daftar objek dengan kunci: no, "
        "kata_kunci, prompt_visual."
        "\n\nADEGAN:\n" + daftar
    )

    arahan_data = tanya_json(ambil_prompt(KODE), instruksi)

    if isinstance(arahan_data, dict):
        arahan_data = arahan_data.get("adegan", [])

    arahan = {
        int(a["no"]): a
        for a in arahan_data
        if isinstance(a, dict) and "no" in a
    }

    # Ambil adegan lama. Footage yang masih tersedia dipertahankan
    # agar pencarian ulang tidak menghapus hasil kerja sebelumnya.
    adegan_lama = db.query(
        """
        SELECT urutan, footage_path, lisensi
        FROM adegan
        WHERE naskah_id=:n
        ORDER BY urutan
        """,
        n=nas["id"],
    )
    lama = {int(x["urutan"]): x for x in adegan_lama}

    hasil_baru = []
    ditemukan = 0
    tidak_ditemukan = 0

    for i, teks in enumerate(bagian):
        a = arahan.get(i, {})
        kata = str(a.get("kata_kunci") or "").strip()
        prompt_visual = str(a.get("prompt_visual") or "").strip()

        path = None
        lisensi = "FOOTAGE BELUM DITEMUKAN - perlu pencarian lanjutan"

        sebelumnya = lama.get(i)
        if sebelumnya:
            path_lama = sebelumnya.get("footage_path")
            if path_lama and os.path.isfile(path_lama):
                path = path_lama
                lisensi = sebelumnya.get("lisensi") or "Lisensi perlu diverifikasi"

        if path:
            ditemukan += 1
        else:
            path_dasar = f"{MEDIA}/{isu_id}/adegan_{i}"
            hasil = _cari_footage(kata, path_dasar) if kata else None

            if hasil:
                path, lisensi = hasil
                ditemukan += 1
            else:
                tidak_ditemukan += 1

        hasil_baru.append({
            "n": nas["id"],
            "u": i,
            "t": teks,
            "p": prompt_visual,
            "f": path,
            "l": lisensi,
            "d": round(len(re.findall(r"\\w+", teks)) / 2.8, 1),
        })

    tahap = (
        "disutradarai"
        if ditemukan == len(bagian)
        else "footage_belum_lengkap"
    )

    # Penggantian adegan dan pembaruan tahap dilakukan dalam SATU transaksi.
    # Jika salah satu INSERT gagal, adegan lama tetap utuh.
    with db.engine.begin() as conn:
        conn.execute(
            text("DELETE FROM adegan WHERE naskah_id=:n"),
            {"n": nas["id"]},
        )

        for item in hasil_baru:
            conn.execute(
                text("""
                    INSERT INTO adegan
                    (naskah_id, urutan, teks, prompt_visual,
                     footage_path, lisensi, durasi_detik)
                    VALUES (:n,:u,:t,:p,:f,:l,:d)
                """),
                item,
            )

        conn.execute(
            text("UPDATE isu SET tahap=:t WHERE id=:i"),
            {"t": tahap, "i": isu_id},
        )

    log(
        KODE,
        f"Hasil penyutradaraan: {ditemukan}/{len(bagian)} footage ditemukan; "
        f"{tidak_ditemukan} belum ditemukan; tahap={tahap}",
        isu_id=isu_id,
        level="info" if tidak_ditemukan == 0 else "warning",
    )

    hasil_kerja = {
        "jumlah_adegan": len(bagian),
        "footage_ditemukan": ditemukan,
        "footage_belum_ditemukan": tidak_ditemukan,
    }

    print(f"[DEDE] Isu {isu_id}: {hasil_kerja}")

    return hasil_kerja
