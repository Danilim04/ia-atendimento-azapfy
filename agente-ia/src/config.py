from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    openrouter_api_key: str = Field(..., alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        "https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    openrouter_model: str = Field(
        "google/gemini-2.5-flash", alias="OPENROUTER_MODEL"
    )
    openrouter_classifier_model: str = Field(
        "google/gemini-2.5-flash-lite", alias="OPENROUTER_CLASSIFIER_MODEL"
    )
    app_referer: str = Field("http://localhost:8000", alias="APP_REFERER")
    app_title: str = Field("Azapfy Suporte IA", alias="APP_TITLE")

    chroma_persist_dir: Path = Field(
        Path("./chroma_db"), alias="CHROMA_PERSIST_DIR"
    )
    docs_dir: Path = Field(Path("./docs"), alias="DOCS_DIR")
    embeddings_model: str = Field(
        "sentence-transformers/all-MiniLM-L6-v2", alias="EMBEDDINGS_MODEL"
    )

    llm_temperature: float = Field(0.2, alias="LLM_TEMPERATURE")
    rag_top_k: int = Field(3, alias="RAG_TOP_K")
    rag_chunk_size: int = Field(800, alias="RAG_CHUNK_SIZE")
    rag_chunk_overlap: int = Field(120, alias="RAG_CHUNK_OVERLAP")

    # Teto de iterações do loop agent⇄tools por turno (defesa contra loops
    # caros: cada iteração é uma chamada cheia ao LLM). O essencial da redução
    # vem da política de tools no system prompt; este é só o limite de guarda.
    agent_max_iteracoes: int = Field(5, alias="AGENT_MAX_ITERACOES")

    # Tools de dados do SAC (abrir/listar chamados) ficam no gateway Go; o agente
    # as chama via HTTP. `sac_tools_token` casa com TOOLS_API_TOKEN do Go.
    sac_tools_base_url: str = Field("http://localhost:8080", alias="SAC_TOOLS_BASE_URL")
    sac_tools_token: str = Field("", alias="SAC_TOOLS_TOKEN")
    sac_tools_timeout: float = Field(30.0, alias="SAC_TOOLS_TIMEOUT")

    # --- Observabilidade: Langfuse (tracing) — OPCIONAL ---
    # Sem as duas chaves, o tracing fica DESLIGADO e o agente roda normal
    # (fail-safe: dev/testes sem rede e o período até as chaves serem preenchidas).
    # Host: https://cloud.langfuse.com (EU) ou https://us.cloud.langfuse.com (US).
    langfuse_public_key: str = Field("", alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field("", alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field("https://cloud.langfuse.com", alias="LANGFUSE_HOST")

    @property
    def langfuse_enabled(self) -> bool:
        """Tracing só liga quando as duas chaves estão presentes."""
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
