from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import get_settings
from src.core.database import engine, Base
from src.api.middleware.tenant import TenantMiddleware
from src.api.routes import (
    auth, cloud_accounts, resources, recommendations, dashboard,
    exports, chat, websocket, jira, compliance, security,
    budgets, reservations, load_balancing, architecture,
)
from src.api.routes import settings as settings_routes
from src.services.realtime_service import start_realtime_service, stop_realtime_service

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    import src.models.tenant  # noqa
    import src.models.cloud_account  # noqa
    import src.models.resource  # noqa
    import src.models.recommendation  # noqa
    import src.models.savings  # noqa
    import src.models.cost_data  # noqa
    import src.models.integration_config  # noqa
    import src.models.compliance  # noqa
    import src.models.security_alert  # noqa
    import src.models.budget  # noqa

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    start_realtime_service()
    yield
    stop_realtime_service()
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Tenant isolation middleware
app.add_middleware(TenantMiddleware)

# Routers
prefix = settings.api_prefix
app.include_router(auth.router, prefix=prefix)
app.include_router(cloud_accounts.router, prefix=prefix)
app.include_router(resources.router, prefix=prefix)
app.include_router(recommendations.router, prefix=prefix)
app.include_router(dashboard.router, prefix=prefix)
app.include_router(exports.router, prefix=prefix)
app.include_router(chat.router, prefix=prefix)
app.include_router(settings_routes.router, prefix=prefix)
app.include_router(jira.router, prefix=prefix)
app.include_router(compliance.router, prefix=prefix)
app.include_router(security.router, prefix=prefix)
app.include_router(budgets.router, prefix=prefix)
app.include_router(reservations.router, prefix=prefix)
app.include_router(load_balancing.router, prefix=prefix)
app.include_router(architecture.router, prefix=prefix)
app.include_router(websocket.router, prefix=prefix)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": settings.app_name}
