from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from coordinator.db.connection import close_pool, get_pool
from coordinator.db.migrate import run_migrations
from coordinator.web.routes import milestones, projects, tasks

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "dashboard" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await get_pool()
    await run_migrations(pool)
    yield
    await close_pool()


app = FastAPI(title="The Hive", lifespan=lifespan)

app.include_router(projects.router, prefix="/api")
app.include_router(milestones.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")

if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
