import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.models.food import HealthResponse
from app.routers import deals, restaurant, search
from app.services.firebase_admin import init_firebase

logging.basicConfig(
    level=logging.INFO if settings.environment == "production" else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting FoodAggregator API...")
    init_firebase(
        service_account_path=settings.firebase_service_account_path,
        service_account_json=settings.firebase_service_account_json,
        project_id=settings.firebase_project_id,
    )
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Allowed origins: {settings.origins}")
    yield
    logger.info("Shutting down FoodAggregator API.")


app = FastAPI(
    title="FoodAggregator API",
    description="Compare food delivery prices across Uber Eats, DoorDash, and Grubhub.",
    version="1.0.0",
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Routers
app.include_router(search.router, prefix="/api", tags=["search"])
app.include_router(restaurant.router, prefix="/api", tags=["restaurant"])
app.include_router(deals.router, prefix="/api", tags=["deals"])


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health():
    return HealthResponse(
        status="ok",
        timestamp=time.time(),
        scrapers={
            "uber_eats": "enabled",
            "doordash": "enabled",
            "grubhub": "enabled",
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again."},
    )
