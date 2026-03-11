from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Firebase
    firebase_project_id: str = ""
    firebase_service_account_path: str = "./serviceAccountKey.json"
    firebase_service_account_json: str = ""

    # App
    environment: str = "development"
    allowed_origins: str = "http://localhost:5173,http://localhost:3000,http://localhost:4173"

    # Scraper tuning
    scraper_timeout_seconds: float = 8.0
    cache_memory_ttl: int = 300       # 5 minutes
    cache_firestore_ttl: int = 1800   # 30 minutes

    @property
    def origins(self) -> List[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    model_config = {"env_file": ".env"}


settings = Settings()
