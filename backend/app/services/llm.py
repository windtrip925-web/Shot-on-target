import json
import os
import re
import time
import urllib.error
import urllib.request


def _kunci():
    key = os.getenv("LLM_API_KEY", "").strip()
    if not key:
        raise RuntimeError("LLM_API_KEY belum diatur.")
    return key


def _isi_pesan(content):
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        bagian = []
        for item in content:
            if isinstance(item, dict):
                teks = item.get("text")
                if isinstance(teks, str):
                    bagian.append(teks)
        return "\n".join(bagian).strip()

    return ""


def _panggil(system, user, max_tokens):
    base = os.getenv("LLM_BASE_URL", "").strip().rstrip("/")
    model = os.getenv("LLM_MODEL", "").strip()

    if not base:
        raise RuntimeError("LLM_BASE_URL belum diatur.")
    if not model:
        raise RuntimeError("LLM_MODEL belum diatur.")

    data = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0.35,
        "messages": [
            {"role": "system", "content": str(system)},
            {"role": "user", "content": str(user)},
        ],
    }

    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + _kunci(),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ShotOnTarget/2.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=150) as response:
            hasil = json.loads(response.read().decode("utf-8"))

    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        raise RuntimeError(
            f"LLM HTTP {exc.code}: {detail}"
        ) from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Koneksi layanan AI gagal: {exc.reason}"
        ) from exc

    choices = hasil.get("choices") or []
    if not choices:
        raise RuntimeError(
            "Layanan AI tidak mengirim pilihan jawaban."
        )

    pilihan = choices[0]
    pesan = pilihan.get("message") or {}
    teks = _isi_pesan(pesan.get("content"))
    alasan = pilihan.get("finish_reason")

    return teks, alasan


def tanya(system, user, max_tokens=2048):
    batas = max(2048, int(max_tokens or 2048))
    batas = min(batas, 12000)
    alasan = None
    kesalahan = None

    while True:
        try:
            teks, alasan = _panggil(system, user, batas)

            if teks and alasan != "length":
                return teks

            if teks and alasan == "length":
                kesalahan = (
                    f"Jawaban terpotong pada {batas} token."
                )
            else:
                kesalahan = (
                    f"Jawaban AI kosong (finish={alasan})."
                )

        except Exception as exc:
            kesalahan = str(exc)

        if batas >= 12000:
            break

        batas = min(batas * 2, 12000)
        time.sleep(1)

    raise RuntimeError(
        f"AI gagal memberikan jawaban lengkap: {kesalahan}"
    )


def _baca_json(teks):
    if isinstance(teks, (dict, list)):
        return teks

    if not isinstance(teks, str) or not teks.strip():
        raise ValueError("Jawaban JSON kosong.")

    bersih = teks.strip()
    bersih = re.sub(
        r"^```(?:json)?\s*",
        "",
        bersih,
        flags=re.IGNORECASE,
    )
    bersih = re.sub(r"\s*```$", "", bersih)

    try:
        return json.loads(bersih)
    except json.JSONDecodeError:
        pass

    # Cari objek atau array JSON di dalam teks tambahan.
    awal_objek = bersih.find("{")
    awal_array = bersih.find("[")

    kandidat = [
        x for x in (awal_objek, awal_array)
        if x >= 0
    ]

    if not kandidat:
        raise ValueError("Jawaban AI tidak mengandung JSON.")

    awal = min(kandidat)
    pembuka = bersih[awal]
    penutup = "}" if pembuka == "{" else "]"

    kedalaman = 0
    dalam_string = False
    escape = False

    for posisi in range(awal, len(bersih)):
        karakter = bersih[posisi]

        if dalam_string:
            if escape:
                escape = False
            elif karakter == "\\":
                escape = True
            elif karakter == '"':
                dalam_string = False
            continue

        if karakter == '"':
            dalam_string = True
        elif karakter == pembuka:
            kedalaman += 1
        elif karakter == penutup:
            kedalaman -= 1
            if kedalaman == 0:
                return json.loads(bersih[awal:posisi + 1])

    raise ValueError("Struktur JSON dari AI tidak lengkap.")


def tanya_json(system, user, max_tokens=3072):
    instruksi = (
        str(system)
        + "\n\nATURAN FORMAT: Keluarkan satu JSON valid saja. "
          "Jangan gunakan Markdown atau teks pembuka."
    )

    teks = tanya(instruksi, user, max_tokens=max_tokens)

    try:
        return _baca_json(teks)
    except (ValueError, json.JSONDecodeError) as exc:
        # Satu kesempatan memperbaiki format tanpa mengubah fakta.
        perbaikan = (
            "Ubah jawaban berikut menjadi JSON valid. "
            "Pertahankan seluruh isi dan jangan menambah fakta. "
            "Keluarkan JSON saja.\n\n"
            + teks[:14000]
        )
        hasil = tanya(
            "Anda adalah pemformat JSON yang ketat.",
            perbaikan,
            max_tokens=max_tokens,
        )
        try:
            return _baca_json(hasil)
        except Exception as akhir:
            raise RuntimeError(
                f"AI menghasilkan JSON yang tidak valid: {akhir}"
            ) from exc
