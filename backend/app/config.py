from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- models -----------------------------------------------------------
    # "echo" is a deterministic stub. It exists so tests and `make eval` run
    # with zero infra; it is not a real provider and the UI labels it as such.
    llm_provider: Literal["ollama", "anthropic", "openai", "echo"] = "ollama"

    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b-instruct"
    ollama_timeout_s: float = 120.0

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5"

    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    # If the primary provider is unreachable, fall back to this one rather than
    # 500ing. Set to None to disable and surface the error instead.
    fallback_provider: Literal["ollama", "anthropic", "openai", "echo", "none"] = "none"

    use_agent_sdk: bool = False  # routes the agent loop through claude-agent-sdk

    # --- storage ----------------------------------------------------------
    database_url: str = "postgresql+asyncpg://lenny:lenny@localhost:5432/lenny"
    vector_backend: Literal["pgvector", "memory"] = "pgvector"

    # --- retrieval --------------------------------------------------------
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_dim: int = 384
    chunk_target_chars: int = 1400
    chunk_overlap_turns: int = 1
    retrieval_top_k: int = 8
    retrieval_candidates: int = 30  # per-arm before RRF fusion
    transcripts_dir: Path = REPO_ROOT / "data" / "transcripts"

    # --- grounding --------------------------------------------------------
    faithfulness_enabled: bool = True
    # Tuned against backend/eval/goldens.yaml, see eval/REPORT.md. Above this a
    # sentence is "supported"; between this and the partial floor it's "partial".
    faithfulness_supported_at: float = 0.65
    faithfulness_partial_at: float = 0.45

    # --- ops --------------------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = True
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
