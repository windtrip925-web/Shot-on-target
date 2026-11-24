import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import edge_tts

from app import db
from app.worker import app
from .base import aman, log

KODE = "suara"
FOLDER = "/media/audio"
SUARA_UTAMA = "id-ID-GadisNeural"
KECEPATAN = "+0%"
PITCH = "+2Hz"
JEDA = 0.35
JEDA_AKHIR = 0.7
JEDA_FRASA = 0.22
BATAS_FRASE = 180


def _kata_perkiraan(teks: str, durasi: float) -> list[dict]:
    daftar = re.findall(r"\S+", teks)
    if not daftar:
        return []

    bobot = []
    for kata in daftar:
        bersih = re.sub(r"[^\w]", "", kata)
        nilai = max(1, len(bersih))
        if re.search(r"[.!?]$", kata):
            nilai += 3
        elif re.search(r"[,;:]$", kata):
            nilai += 1.5
        bobot.append(nilai)

    total = sum(bobot)
    posisi = 0.0
    hasil = []

    for kata, nilai in zip(daftar, bobot):
        panjang = durasi * nilai / total
        hasil.append({
            "w": kata,
            "s": round(posisi, 3),
            "e": round(posisi + panjang, 3),
        })
        posisi += panjang

    return hasil


async def _edge_stream(teks: str, mp3_path: str, rate=None) -> list[dict]:
    komunikasi = edge_tts.Communicate(
        teks,
        voice=SUARA_UTAMA,
        rate=rate or KECEPATAN,
        pitch=PITCH,
    )

    batas_kata = []

    with open(mp3_path, "wb") as audio:
        async for bagian in komunikasi.stream():
            if bagian["type"] == "audio":
                audio.write(bagian["data"])
            elif bagian["type"] == "WordBoundary":
                batas_kata.append({
                    "w": str(bagian.get("text", "")).strip(),
                    "s": float(bagian["offset"]) / 10_000_000,
                    "e": (
                        float(bagian["offset"])
                        + float(bagian["duration"])
                    ) / 10_000_000,
                })

    return [x for x in batas_kata if x["w"]]


def _konversi_wav(sumber: str, tujuan: str):
    p = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", sumber,
            "-ac", "1",
            "-ar", "44100",
            "-c:a", "pcm_s16le",
            tujuan,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if p.returncode != 0:
        raise RuntimeError(f"Konversi audio gagal: {p.stderr[-800:]}")


def _durasi(path: str) -> float:
    p = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0", path,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    nilai = float(p.stdout.strip())
    if nilai <= 0:
        raise ValueError("Durasi audio tidak valid")
    return nilai


def _buat_espeak(teks: str, path: str):
    mesin = shutil.which("espeak-ng")
    if not mesin:
        raise RuntimeError("Edge TTS gagal dan eSpeak NG tidak tersedia")

    subprocess.run(
        [
            mesin, "-v", "id",
            "-s", "145",
            "-p", "58",
            "-a", "170",
            "-w", path,
            teks,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    durasi = _durasi(path)
    return _kata_perkiraan(teks, durasi), durasi, "eSpeak NG fallback"



def _pecah_frasa(teks: str) -> list[str]:
    """Memecah narasi menjadi frasa yang lebih mudah dibawakan."""
    teks = re.sub(r"\s+", " ", teks).strip()
    if not teks:
        return []

    kalimat = re.split(r"(?<=[.!?…;:])\s+", teks)
    hasil = []

    for bagian in kalimat:
        bagian = bagian.strip()
        if not bagian:
            continue

        if len(bagian) <= BATAS_FRASE:
            hasil.append(bagian)
            continue

        # Untuk kalimat panjang, utamakan batas koma.
        potongan = re.split(r"(?<=,)\s+", bagian)
        sementara = ""

        for pot in potongan:
            if not sementara:
                sementara = pot
            elif len(sementara) + len(pot) + 1 <= BATAS_FRASE:
                sementara += " " + pot
            else:
                hasil.append(sementara.strip())
                sementara = pot

        if sementara:
            hasil.append(sementara.strip())

    return hasil


def _buat_sunyi(path: str, durasi: float):
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=mono",
            "-t", str(durasi),
            "-c:a", "pcm_s16le",
            path,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )


def _gabung_wav(daftar: list[str], tujuan: str):
    daftar_path = str(Path(tujuan).with_suffix(".txt"))

    with open(daftar_path, "w", encoding="utf-8") as f:
        for nama in daftar:
            f.write(f"file '{nama}'\n")

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0",
                "-i", daftar_path,
                "-c:a", "pcm_s16le",
                tujuan,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=180,
        )
    finally:
        if os.path.exists(daftar_path):
            os.remove(daftar_path)


def _buat_audio(teks: str, path: str):
    """Membuat suara per frasa dan mempertahankan timestamp kata."""
    os.makedirs(os.path.dirname(path), exist_ok=True)

    frasa = _pecah_frasa(teks)
    if not frasa:
        raise ValueError("Narasi kosong")

    with tempfile.TemporaryDirectory(prefix="marno_") as folder:
        daftar_wav = []
        semua_kata = []
        offset = 0.0

        for i, bagian in enumerate(frasa):
            mp3 = os.path.join(folder, f"frasa_{i}.mp3")
            wav = os.path.join(folder, f"frasa_{i}.wav")

            # Frasa pendek sedikit lebih cepat; frasa panjang lebih tenang.
            rate = "+2%" if len(bagian) < 75 else "-2%"

            batas = asyncio.run(
                _edge_stream(bagian, mp3, rate=rate)
            )

            if not os.path.isfile(mp3) or os.path.getsize(mp3) < 100:
                raise RuntimeError(
                    f"Edge TTS gagal membuat audio frasa {i + 1}"
                )

            _konversi_wav(mp3, wav)
            durasi_frasa = _durasi(wav)

            if not batas:
                batas = _kata_perkiraan(bagian, durasi_frasa)

            for item in batas:
                mulai = max(0.0, min(float(item["s"]), durasi_frasa))
                akhir = max(mulai, min(float(item["e"]), durasi_frasa))

                if item["w"] and akhir > mulai:
                    semua_kata.append({
                        "w": item["w"],
                        "s": round(offset + mulai, 3),
                        "e": round(offset + akhir, 3),
                    })

            daftar_wav.append(wav)
            offset += durasi_frasa

            # Jeda nyata di antara frasa, bukan hanya jeda subtitle.
            if i < len(frasa) - 1:
                sunyi = os.path.join(folder, f"jeda_{i}.wav")
                _buat_sunyi(sunyi, JEDA_FRASA)
                daftar_wav.append(sunyi)
                offset += JEDA_FRASA

        hasil_sementara = os.path.join(folder, "hasil.wav")
        _gabung_wav(daftar_wav, hasil_sementara)

        durasi = _durasi(hasil_sementara)
        if durasi <= 0 or not semua_kata:
            raise RuntimeError("Audio atau timestamp kata tidak valid")

        # Validasi bahwa timestamp tidak melewati durasi audio.
        for item in semua_kata:
            item["s"] = round(max(0, min(item["s"], durasi)), 3)
            item["e"] = round(max(item["s"], min(item["e"], durasi)), 3)

        semua_kata = [
            k for k in semua_kata if k["e"] > k["s"]
        ]

        if not semua_kata:
            raise RuntimeError("Tidak ada timestamp subtitle yang valid")

        # Salin hasil final setelah seluruh proses berhasil.
        shutil.copy2(hasil_sementara, path)

    return semua_kata, durasi, "Microsoft Edge TTS " + SUARA_UTAMA


@app.task(
    name="app.karyawan.marno_suara.jalankan",
    bind=True,
    max_retries=3,
)
@aman(KODE)
def jalankan(self, isu_id: int):
    naskah = db.query(
        """
        SELECT id FROM naskah
        WHERE isu_id=:i
        ORDER BY versi DESC
        LIMIT 1
        """,
        i=isu_id,
    )
    if not naskah:
        raise ValueError(f"Naskah isu {isu_id} tidak ditemukan")

    adegan = db.query(
        """
        SELECT id, urutan, teks, audio_path, kata, durasi_detik
        FROM adegan
        WHERE naskah_id=:n
        ORDER BY urutan
        """,
        n=naskah[0]["id"],
    )
    if not adegan:
        raise ValueError("Belum ada adegan untuk dibuatkan suara")

    status_isu = db.query(
        "SELECT tahap FROM isu WHERE id=:i",
        i=isu_id,
    )
    if not status_isu:
        raise ValueError(f"Isu {isu_id} tidak ditemukan")

    tahap_sekarang = status_isu[0]["tahap"]
    if tahap_sekarang in {
        "menunggu_persetujuan",
        "disetujui",
        "dipublish",
        "ditolak",
    }:
        raise ValueError(
            f"Isu sudah berada pada tahap {tahap_sekarang}; "
            "Marno tidak boleh mengubah produksi yang telah selesai"
        )

    total = 0.0
    mesin_dipakai = set()
    dibuat = 0

    for idx, a in enumerate(adegan):
        # Versi Gadis disimpan terpisah; audio lama tetap menjadi cadangan.
        path = (
            f"{FOLDER}/{isu_id}/"
            f"adegan_{a['urutan']}_gadis.wav"
        )

        if (
            a["audio_path"] == path
            and a["kata"]
            and os.path.isfile(path)
        ):
            total += float(a["durasi_detik"] or 0)
            mesin_dipakai.add("Microsoft Edge TTS " + SUARA_UTAMA)
            continue

        teks = str(a["teks"] or "").strip()
        if not teks:
            raise ValueError(f"Teks adegan {a['urutan']} kosong")

        kata, durasi, mesin = _buat_audio(teks, path)
        jeda = JEDA_AKHIR if idx == len(adegan) - 1 else JEDA
        durasi_final = round(durasi + jeda, 2)

        db.execute(
            """
            UPDATE adegan
            SET audio_path=:p,
                kata=CAST(:k AS JSONB),
                durasi_detik=:d
            WHERE id=:i
            """,
            p=path,
            k=json.dumps(kata, ensure_ascii=False),
            d=durasi_final,
            i=a["id"],
        )

        total += durasi_final
        dibuat += 1
        mesin_dipakai.add(mesin)

        log(
            KODE,
            f"Audio adegan {a['urutan']} selesai menggunakan {mesin}",
            isu_id=isu_id,
        )

    db.execute(
        """
        UPDATE isu SET tahap='disuarakan'
        WHERE id=:i
          AND tahap NOT IN (
            'menunggu_persetujuan',
            'disetujui',
            'dipublish',
            'ditolak'
          )
        """,
        i=isu_id,
    )

    return {
        "isu_id": isu_id,
        "jumlah_adegan": len(adegan),
        "audio_diperbarui": dibuat,
        "durasi_total": round(total, 1),
        "mesin_suara": sorted(mesin_dipakai),
        "suara_utama": SUARA_UTAMA,
    }
