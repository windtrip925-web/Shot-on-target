import os, re, json, time
import httpx

BASE = "https://openrouter.ai/api/v1"
_cache = {"model": []}


def _kunci():
    k = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not k:
        raise RuntimeError("OPENROUTER_API_KEY kosong di .env")
    return k


def model_gratis():
    if _cache["model"]:
        return _cache["model"]
    pilih = os.environ.get("OPENROUTER_MODEL", "").strip()
    hasil = [pilih] if pilih.endswith(":free") else []
    r = httpx.get(BASE + "/models", timeout=30)
    r.raise_for_status()
    ada = []
    for m in r.json().get("data", []):
        p = m.get("pricing", {})
        if str(p.get("prompt")) == "0" and str(p.get("completion")) == "0" and m["id"].endswith(":free"):
            ada.append((m.get("context_length") or 0, m["id"]))
    ada.sort(reverse=True)
    hasil += [i for _, i in ada if i not in hasil][:5]
    _cache["model"] = hasil
    return hasil


def tanya(system, user, max_tokens=3000):
    kepala = {"Authorization": "Bearer " + _kunci(),
              "Content-Type": "application/json"}
    galat = []
    for model in model_gratis():
        body = {"model": model, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}]}
        try:
            r = httpx.post(BASE + "/chat/completions", headers=kepala,
                           json=body, timeout=90)
            if r.status_code == 200:
                teks = r.json()["choices"][0]["message"]["content"]
                if teks and teks.strip():
                    return teks
                galat.append(f"{model}: kosong")
            else:
                galat.append(f"{model}: {r.status_code}")
                if r.status_code == 429:
                    time.sleep(5)
        except Exception as e:
            galat.append(f"{model}: {e}")
    raise RuntimeError("semua model gratis gagal: " + " | ".join(galat))


def tanya_json(system, user, max_tokens=3000):
    teks = tanya(system + "\n\nJawab HANYA JSON valid, tanpa teks lain.",
                 user, max_tokens)
    teks = re.sub(r"^\x60\x60\x60(?:json)?|\x60\x60\x60$", "",
                  teks.strip(), flags=re.M).strip()
    try:
        return json.loads(teks)
    except ValueError:
        m = re.search(r"(\{.*\}|\[.*\])", teks, re.S)
        if not m:
            raise
        return json.loads(m.group(1))
