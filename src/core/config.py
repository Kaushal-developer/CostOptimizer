from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_name: str = "CostOptimizer"
    environment: str = "development"
    debug: bool = False
    secret_key: str = "change-me-in-production"
    api_prefix: str = "/api/v1"

    # Database
    database_url: str = "postgresql+asyncpg://costopt:costopt@localhost:5432/costoptimizer"
    database_pool_size: int = 5
    database_max_overflow: int = 5

    # Redis (optional — workers won't start without it, but API works fine)
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # Auth
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # AWS
    aws_external_id_prefix: str = "costopt"

    # Azure
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""

    # GCP
    gcp_credentials_path: str = ""

    # Anthropic (LLM)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # Local LLM (ollama/vllm — OpenAI-compatible API)
    local_llm_url: str = "http://localhost:11434"  # default ollama URL
    local_llm_model: str = "qwen2.5:3b"
    llm_provider: str = "auto"  # "claude", "local", "auto" (tries claude -> local -> template)

    # Feature flags
    enable_auto_remediation: bool = False
    enable_ml_predictions: bool = True

    model_config = {"env_prefix": "COSTOPT_", "env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
