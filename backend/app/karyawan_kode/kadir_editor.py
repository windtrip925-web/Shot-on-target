
import glob
import os
import random
import subprocess

from app import db
from app.worker import app
from .base import aman, log

KODE = "editor"
HASIL = "/media/hasil"
MUSIK = "/media/musik"

WARNA = [
    "0x123B2A",
    "0x142D50",
    "0x48251B",
    "0x30204F",
    "0x12443F",
    "0x501D35",
]

ASS_HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Utama,DejaVu Sans,84,&H0000E5FF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,2,60,60,520,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ff(args):
    p = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args,
        capture_output=True,
        text=True,
        timeout=900,
    )
    if p.returncode != 0:
        raise RuntimeError(f"FFmpeg gagal: {p.stderr[-1200:]}")


def _t(d):
    cs = int(round(d * 100))
    return (
        f"{cs // 360000}:"
        f"{cs % 360000 // 6000:02d}:"
        f"{cs % 6000 // 100:02d}.{cs % 100:02d}"
    )


def _buat_ass(adegan, path):
    baris = []
    offset = 0.0

    for a in adegan:
        potong = []
        cur = []

        for k in (a["kata"] or []):
            if not k.get("w"):
                continue

            cur.append(k)

            if len(cur) >= 3 or k["w"][-1] in ".,!?…":
                potong.append(cur)
                cur = []

        if cur:
            potong.append(cur)

        for i, g in enumerate(potong):
            mulai = offset + float(g[0]["s"])
            akhir = offset + float(g[-1]["e"]) + 0.25

            if i + 1 < len(potong):
                akhir = min(
                    akhir,
                    offset + float(potong[i + 1][0]["s"]),
                )

            teks = ""

            for j, k in enumerate(g):
                sel = (
                    float(g[j + 1]["s"]) - float(k["s"])
                    if j + 1 < len(g)
                    else float(k["e"]) - float(k["s"])
                )

                teks += (
                    f"{{\\k{max(1, round(sel * 100))}}}"
                    f"{k['w'].upper()} "
                )

            if akhir > mulai:
                baris.append(
                    f"Dialogue: 0,{_t(mulai)},{_t(akhir)},"
                    f"Utama,,0,0,0,,{teks.strip()}"
                )

        offset += float(a["durasi_detik"])

    with open(path, "w", encoding="utf-8") as f:
        f.write(ASS_HEAD + "\n".join(baris) + "\n")


def _grafis_sepakbola(i, a, folder):
    """
    Membuat visual grafis sepak bola bergerak tanpa footage/API.
    """

    dur = float(a["durasi_detik"])
    keluar = f"{folder}/seg_{i}.mp4"

    teks = str(a.get("teks") or "CERITA SEPAK BOLA")
    teks = teks.replace("\n", " ").strip()[:100]

    teks_path = f"{folder}/judul_{i}.txt"

    with open(teks_path, "w", encoding="utf-8") as f:
        f.write(teks)

    warna = WARNA[i % len(WARNA)]

    # Lapangan, garis tengah, kotak penalti, dan bola bergerak.
    vf = (
        "drawbox=x=65:y=230:w=950:h=1450:"
        "color=white@0.8:t=7,"
        "drawbox=x=65:y=950:w=950:h=7:"
        "color=white@0.8:t=5,"
        "drawbox=x=260:y=230:w=560:h=240:"
        "color=white@0.8:t=6,"
        "drawbox=x=260:y=1440:w=560:h=240:"
        "color=white@0.8:t=6,"
        "drawbox=x=390:y=820:w=300:h=260:"
        "color=white@0.7:t=6,"
        "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        "text='SHOT ON TARGET':"
        "fontcolor=white:fontsize=48:x=(w-text_w)/2:y=95,"
        "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        f"textfile={teks_path}:"
        "fontcolor=yellow:fontsize=48:"
        "borderw=3:bordercolor=black:"
        "x=(w-text_w)/2:y=350:"
        "line_spacing=18,"
        "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        "text='●':fontcolor=white:fontsize=110:"
        "borderw=5:bordercolor=black:"
        "x='100+mod(t*230,750)':"
        "y='1050+100*sin(t*3)',"
        "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        "text='ANALISIS SEPAK BOLA':"
        "fontcolor=white:fontsize=35:"
        "x=(w-text_w)/2:y=1780,"
        "setsar=1,fps=30"
    )

    ff([
        "-f", "lavfi",
        "-i", f"color=c={warna}:s=1080x1920:r=30:d={dur}",
        "-i", a["audio_path"],
        "-t", str(dur),
        "-vf", vf,
        "-af", f"apad=whole_dur={dur},aresample=44100",
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-c:a", "aac",
        "-ar", "44100",
        "-ac", "2",
        keluar,
    ])

    return keluar


def _segmen(i, a, folder):
    dur = float(a["durasi_detik"])
    keluar = f"{folder}/seg_{i}.mp4"

    footage = a.get("footage_path")

    if footage and os.path.isfile(footage):
        ff([
            "-stream_loop", "-1",
            "-i", footage,
            "-i", a["audio_path"],
            "-t", str(dur),
            "-vf",
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,setsar=1,fps=30",
            "-af", f"apad=whole_dur={dur},aresample=44100",
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            "-c:a", "aac",
            "-ar", "44100",
            "-ac", "2",
            keluar,
        ])

        return keluar

    return _grafis_sepakbola(i, a, folder)


@app.task(
    name="app.karyawan.kadir_editor.jalankan",
    bind=True,
    max_retries=3,
)
@aman(KODE)
def jalankan(self, isu_id):
    rows = db.query(
        """

        SELECT id
        FROM naskah
        WHERE isu_id=:i
        ORDER BY versi DESC
        LIMIT 1
        """,
        i=isu_id,
    )

    if not rows:
        raise ValueError("Naskah tidak ditemukan")

    nas = rows[0]

    adegan = db.query(
        """
        SELECT *
        FROM adegan
        WHERE naskah_id=:n
        ORDER BY urutan
        """,
        n=nas["id"],
    )

    if not adegan:
        raise ValueError("Adegan belum tersedia")

    for a in adegan:
        if not a["audio_path"] or not os.path.isfile(a["audio_path"]):
            raise ValueError(
                f"Audio adegan {a['urutan']} belum tersedia"
            )

        if not a["kata"]:
            raise ValueError(
                f"Data subtitle adegan {a['urutan']} belum tersedia"
            )

    total = sum(float(a["durasi_detik"]) for a in adegan)

    if total > 75:
        raise ValueError(f"Video terlalu panjang: {total:.0f} detik")

    if not 28 <= total <= 48:
        log(
            KODE,
            f"Durasi {total:.0f} detik di luar target 30-45",
            isu_id=isu_id,
            level="warn",
        )

    folder = f"{HASIL}/{isu_id}"
    os.makedirs(folder, exist_ok=True)

    segmen = []

    try:
        for i, a in enumerate(adegan):
            segmen.append(_segmen(i, a, folder))

        daftar = f"{folder}/daftar.txt"

        with open(daftar, "w", encoding="utf-8") as f:
            for s in segmen:
                f.write(f"file '{s}'\n")

        gabung = f"{folder}/gabung.mp4"

        ff([
            "-f", "concat",
            "-safe", "0",
            "-i", daftar,
            "-c", "copy",
            gabung,
        ])

        ass = f"{folder}/sub.ass"
        _buat_ass(adegan, ass)

        lagu = glob.glob(f"{MUSIK}/*.mp3")
        masuk = ["-i", gabung]
        filter_complex = f"[0:v]ass={ass}[v];"
        nama_lagu = None

        if lagu:
            pilih = random.choice(lagu)
            nama_lagu = os.path.basename(pilih)

            masuk += ["-stream_loop", "-1", "-i", pilih]

            filter_complex += (
                "[1:a]volume=0.12[m];"
                "[0:a][m]amix=inputs=2:duration=first:"
                "normalize=0[a0];"
                f"[a0]afade=t=out:st={max(total - 1, 0):.2f}:d=1[a]"
            )
        else:
            log(
                KODE,
                "Folder musik kosong, video tanpa musik latar",
                isu_id=isu_id,
                level="warn",
            )

            filter_complex += (
                f"[0:a]afade=t=out:st={max(total - 1, 0):.2f}:d=1[a]"
            )

        final = f"{folder}/final.mp4"

        ff(
            masuk + [
                "-filter_complex", filter_complex,
                "-map", "[v]",
                "-map", "[a]",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "21",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "160k",
                "-movflags", "+faststart",
                final,
            ]
        )

        thumb = f"{folder}/thumb.jpg"

        ff([
            "-ss", "1",
            "-i", final,
            "-frames:v", "1",
            thumb,
        ])

        db.execute(
            "DELETE FROM media WHERE isu_id=:i",
            i=isu_id,
        )

        for jenis, path in (
            ("video", final),
            ("subtitle", ass),
            ("thumbnail", thumb),
        ):
            db.execute(
                """
                INSERT INTO media (isu_id, jenis, path)
                VALUES (:i,:j,:p)
                """,
                i=isu_id,
                j=jenis,
                p=path,
            )

        db.execute(
            """
            UPDATE isu
            SET tahap='menunggu_persetujuan'
            WHERE id=:i
            """,
            i=isu_id,
        )

        return {
            "durasi": round(total, 1),
            "musik": nama_lagu or "tanpa musik",
            "visual_footage": sum(
                1 for a in adegan
                if a.get("footage_path")
                and os.path.isfile(a["footage_path"])
            ),
            "visual_grafis": sum(
                1 for a in adegan
                if not a.get("footage_path")
                or not os.path.isfile(a["footage_path"])
            ),
        }

    finally:
        for s in segmen:
            if os.path.exists(s):
                os.remove(s)

        gabung = f"{folder}/gabung.mp4"
        if os.path.exists(gabung):
            os.remove(gabung)
