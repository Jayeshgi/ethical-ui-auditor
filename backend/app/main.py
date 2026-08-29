from fastapi import FastAPI, HTTPException
from sqlalchemy import text

from app.api.routes import router
from app.auth.routes import router as auth_router
from app.core.config import VISUAL_MODEL_PATH, configure_runtime_environment
from app.database import engine, initialize_database
from app.flow_analysis.benchmarks import router as flow_benchmark_router
from app.flow_analysis.autonomous_routes import router as autonomous_flow_router
from app.flow_analysis.routes import router as flow_router
from app.flow_analysis.ui import router as flow_ui_router
from app.text_analysis.model import MODEL_ARTIFACT_DIR


configure_runtime_environment()
initialize_database()
app = FastAPI(title="Ethical UI Auditor", version="0.1.0", description="Read-only developer scan for candidate dark-pattern language.")
app.include_router(auth_router)
app.include_router(router)
app.include_router(autonomous_flow_router)
app.include_router(flow_router)
app.include_router(flow_benchmark_router)
app.include_router(flow_ui_router)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
async def ready() -> dict[str, object]:
    checks = {
        "database": False,
        "bert_artifact": (MODEL_ARTIFACT_DIR / "metadata.json").exists() and (MODEL_ARTIFACT_DIR / "thresholds.json").exists(),
        "visual_artifact": VISUAL_MODEL_PATH.exists(),
    }
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        pass
    if not all(checks.values()):
        raise HTTPException(status_code=503, detail={"status": "not_ready", "checks": checks})
    return {"status": "ready", "checks": checks}
