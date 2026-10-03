from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routes import router

app = FastAPI(
    title="RTO Risk Scorer",
    version="0.1.0",
    description="Multi-agent AI pipeline for COD order RTO risk assessment"
)

# CORS: Restricted for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict in production
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Exception handler for validation errors
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Format 422 validation errors as readable strings instead of [object Object]."""
    errors = []
    for err in exc.errors():
        loc = " -> ".join(str(x) for x in err["loc"])
        msg = err["msg"]
        errors.append(f"{loc}: {msg}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "; ".join(errors)},
    )

# Register routes
app.include_router(router)

# Serve frontend static files
FRONTEND_DIR = Path(__file__).parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    async def serve_frontend() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/dev")
    async def serve_dev_console() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "dev.html")
