import json
import re
import anthropic
from ..config import settings

_client = None

def _get():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client

def tanya(system: str, user: str, max_tokens: int = 2000) -> str:
    r = _get().messages.create(
        model=settings.LLM_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return r.content[0].text

def tanya_json(system: str, user: str, max_tokens: int = 3000):
    teks = tanya(system + "\n\nJawab HANYA JSON valid, tanpa teks lain.", user, max_tokens)
    teks = re.sub(r"^```(?:json)?|```$", "", teks.strip(), flags=re.M).strip()
    return json.loads(teks)