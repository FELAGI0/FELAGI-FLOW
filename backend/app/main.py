from fastapi import FastAPI

from app.shared.logging import setup_logging

setup_logging()

app = FastAPI(title="Felagi Flow")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
