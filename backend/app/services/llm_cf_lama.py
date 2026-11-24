import os, json, urllib.request, urllib.error


def _kunci():
    k = os.getenv("LLM_API_KEY", "")
    if not k:
        raise RuntimeError("LLM_API_KEY kosong di .env")
    return k


def tanya(system, user, max_tokens=1000):
    base = os.getenv("LLM_BASE_URL", "https://models.github.ai/inference")
    data = {
        "model": os.getenv("LLM_MODEL", "openai/gpt-4.1-mini"),
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    kepala = {
        "Authorization": "Bearer " + _kunci(),
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(data).encode(),
        headers=kepala,
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            hasil = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError("LLM HTTP %s: %s" % (e.code, e.read().decode()[:200]))
    return hasil["choices"][0]["message"]["content"].strip()


def tanya_json(system, user, max_tokens=1000):
    teks = tanya(system, user, max_tokens)
    teks = teks.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(teks)
    except ValueError:
        awal = min([i for i in (teks.find("{"), teks.find("[")) if i >= 0] or [0])
        akhir = max(teks.rfind("}"), teks.rfind("]")) + 1
        return json.loads(teks[awal:akhir])
