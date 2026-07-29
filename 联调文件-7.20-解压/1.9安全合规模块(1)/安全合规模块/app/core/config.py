from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = Field(default="security-compliance-check", alias="APP_NAME")
    app_env: str = Field(default="dev", alias="APP_ENV")
    data_file: str = Field(default="./data/mock_data.json", alias="DATA_FILE")
    sqlite_db: str = Field(default="./data/security_audit.db", alias="SQLITE_DB")

    # Guardrail backend: "in_house" only for this standalone module
    guardrail_backend: str = Field(default="in_house", alias="GUARDRAIL_BACKEND")
    # Custom banned words (comma-separated)
    llm_guard_custom_banned_words: str = Field(default="", alias="LLM_GUARD_CUSTOM_BANNED_WORDS")

    # Category-level semantic similarity (optional, requires sentence-transformers)
    category_semantic_enabled: bool = Field(default=False, alias="CATEGORY_SEMANTIC_ENABLED")
    category_semantic_threshold: float = Field(default=0.60, alias="CATEGORY_SEMANTIC_THRESHOLD")
    embedding_similarity_enabled: bool = Field(default=False, alias="EMBEDDING_SIMILARITY_ENABLED")
    embedding_similarity_threshold: float = Field(default=0.80, alias="EMBEDDING_SIMILARITY_THRESHOLD")
    embedding_model_name: str = Field(default="paraphrase-multilingual-MiniLM-L12-v2", alias="EMBEDDING_MODEL_NAME")

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def data_path(self) -> Path:
        return Path(self.data_file)

    @property
    def db_path(self) -> Path:
        return Path(self.sqlite_db)

    @property
    def llm_guard_custom_banned_list(self) -> list[str]:
        return [x.strip() for x in self.llm_guard_custom_banned_words.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
