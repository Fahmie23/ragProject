from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "RAG Document Pipeline API"
    data_dir: Path = Path("data")
    max_upload_mb: int = 50

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

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


settings = Settings()
for directory in (
    settings.raw_dir,
    settings.metadata_dir,
    settings.extracted_dir,
    settings.layout_dir,
    settings.structured_dir,
    settings.corrections_dir,
    settings.resolved_dir,
):
    directory.mkdir(parents=True, exist_ok=True)
