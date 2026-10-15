"""API веб-админки: python -m api.main  (или uvicorn api.main:app)

Отдаёт и собранный фронтенд из admin/dist, так что в проде это один процесс.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api import auth, dashboard, sources_api, users_api
from api.system import sampler
from common.config import get_settings
from search.orchestrator import SearchService, sync_source_configs

log = logging.getLogger("aviawatch.api")
DIST = Path(__file__).resolve().parent.parent.parent / "admin" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await sync_source_configs()
    app.state.svc = SearchService()
    sampler.start()
    yield
    await sampler.stop()
    await app.state.svc.close()


app = FastAPI(title="AviaWatch admin API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (auth.router, dashboard.router, sources_api.router, users_api.router):
    app.include_router(r)


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True}


if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        file = DIST / path
        if path and file.is_file():
            return FileResponse(file)
        return FileResponse(DIST / "index.html")


def main() -> None:
    import uvicorn

    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run("api.main:app", host="0.0.0.0", port=settings.api_port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    main()
