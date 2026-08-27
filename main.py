from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.clients import close_clients
# from core.orchestrator import run_pipeline_async  # unused
# from api.routes import router as api_router  # empty, not yet implemented


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_clients()


app = FastAPI(
    title="RTO Risk Scorer",
    version="0.1.0",
    description="Multi-agent AI pipeline for COD order RTO risk assessment",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
