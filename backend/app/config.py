from pathlib import Path
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "RAG Document Pipeline API"
    data_dir: Path = Path("data")
    max_upload_mb: int = 50
    database_url: str | None = None
    database_required: bool = False
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "auto"
    embedding_batch_size: int = 8
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_device: str = "auto"
    reranker_batch_size: int = 2
    reranker_max_length: int = 1024

    # Stage 9 grounded answer generation. Groq is the default provider, but the
    # client speaks the OpenAI-compatible chat-completions protocol so the base
    # URL/model can be replaced through environment variables without touching
    # retrieval code.
    generation_provider: str = "groq"
    generation_base_url: str = "https://api.groq.com/openai/v1"
    generation_model: str = "llama-3.3-70b-versatile"
    generation_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GENERATION_API_KEY", "GROQ_API_KEY"),
        repr=False,
    )
    generation_timeout_seconds: float = 90.0
    generation_temperature: float = 0.0
    generation_max_tokens: int = 1200
    generation_json_mode: bool = True
    generation_max_context_chars: int = 40000

    # The repository-level .env also contains Docker Compose variables such as
    # POSTGRES_DB/BACKEND_PORT. They are valid project configuration even though
    # this Settings model does not consume them directly, so ignore unrelated
    # dotenv keys instead of making local scripts/tests fail when run from the
    # repository root.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def metadata_dir(self) -> Path:
        return self.data_dir / "metadata"

    @property
    def extracted_dir(self) -> Path:
        return self.data_dir / "extracted"

    @property
    def layout_dir(self) -> Path:
        return self.data_dir / "layout"

    @property
    def structured_dir(self) -> Path:
        return self.data_dir / "structured"

    @property
    def corrections_dir(self) -> Path:
        return self.data_dir / "corrections"

    @property
    def resolved_dir(self) -> Path:
        return self.data_dir / "resolved"

    @property
    def chunks_dir(self) -> Path:
        return self.data_dir / "chunks"


settings = Settings()
for directory in (
    settings.raw_dir,
    settings.metadata_dir,
    settings.extracted_dir,
    settings.layout_dir,
    settings.structured_dir,
    settings.corrections_dir,
    settings.resolved_dir,
    settings.chunks_dir,
):
    directory.mkdir(parents=True, exist_ok=True)
