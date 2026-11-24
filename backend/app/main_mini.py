from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings

api = FastAPI(title="Shot on Target")
api.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


@api.get("/health")
def health():
    return {"ok": True}
