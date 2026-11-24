import time, functools, traceback
from pathlib import Path
from .. import db

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


def log(kode, pesan, isu_id=None, level="info"):
    print(f"[{kode}] {pesan}", flush=True)
    try:
        db.execute(
            "INSERT INTO tugas_log (karyawan_kode, isu_id, level, pesan) "
            "VALUES (:k, :i, :l, :p)",
            k=kode, i=isu_id, l=level, p=str(pesan)[:1000],
        )
    except Exception as e:
        print(f"(log DB gagal: {e})", flush=True)


def ambil_prompt(nama):
    f = PROMPT_DIR / f"{nama}.txt"
    if not f.exists():
        f = PROMPT_DIR / f"{nama}.md"
    return f.read_text(encoding="utf-8") + "\n\n" + _gaya()


def aman(kode, maks_coba=3, jeda=5):
    def hias(fn):
        @functools.wraps(fn)
        def bungkus(*a, **kw):
            for ke in range(1, maks_coba + 1):
                try:
                    return fn(*a, **kw)
                except Exception as e:
                    log(kode, f"gagal {ke}/{maks_coba}: {e}", level="error")
                    if ke == maks_coba:
                        log(kode, traceback.format_exc()[-800:], level="error")
                        raise
                    time.sleep(jeda * ke)
        return bungkus
    return hias


PETA_TAHAP = {
    "baru":         "app.karyawan.agim_perekap.jalankan",
    "direkap":      "app.karyawan.noval_factcheck.jalankan",
    "dicek":        "app.karyawan.khotib_penulis.jalankan",
    "ditulis":      "app.karyawan.dede_sutradara.jalankan",
    "footage_belum_lengkap": "app.karyawan.dede_sutradara.jalankan",
    "disutradarai": "app.karyawan.marno_suara.jalankan",
    "disuarakan":   "app.karyawan.kadir_editor.jalankan",
    # "disetujui":  "app.karyawan.syair_publisher.jalankan",  # Langkah 7
}

def _gaya():
    f = PROMPT_DIR / "gaya.txt"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def _gaya():
    f = PROMPT_DIR / "gaya.txt"
    return f.read_text(encoding="utf-8") if f.exists() else ""
