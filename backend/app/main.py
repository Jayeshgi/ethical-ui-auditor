from fastapi import FastAPI

from app.api.routes import router
from app.core.config import configure_runtime_environment


configure_runtime_environment()
app = FastAPI(title="Ethical UI Auditor", version="0.1.0", description="Read-only developer scan for candidate dark-pattern language.")
app.include_router(router)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}

