"""Typed access to config.yaml plus secrets from the environment / .env."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class NodeLLM(BaseModel):
    temperature: float | None = None
    num_predict: int = 2000


class LLMConfig(BaseModel):
    base_url: str
    model: str
    num_ctx: int
    timeout_s: float
    concurrency: int
    default_temperature: float
    nodes: dict[str, NodeLLM]
    embed_model: str
    embed_keep_alive: str

    def node(self, name: str) -> NodeLLM:
        cfg = self.nodes.get(name, NodeLLM())
        if cfg.temperature is None:
            cfg = cfg.model_copy(update={"temperature": self.default_temperature})
        return cfg


class Limits(BaseModel):
    max_pages: int
    max_bytes: int
    max_text_chars: int
    script_token_budget: int


class AltConfig(BaseModel):
    variants: int
    rescore_runs: int
    excerpt_elements: int
    max_span: int


class PipelineConfig(BaseModel):
    engagement_runs: int
    suggestions_min: int
    suggestions_max: int
    alternatives: AltConfig


class OCRConfig(BaseModel):
    doc_qna_url: str
    low_conf_page: float
    low_conf_line: float
    low_line_share: float
    unreadable_conf: float
    max_dpi: int
    local_device: str = "cpu"


class ServerConfig(BaseModel):
    api_host: str
    api_port: int
    ui_port: int
    queue_max: int
    retention_days: int


class Paths(BaseModel):
    data_dir: Path
    knowledge_dir: Path
    prompts_dir: Path
    examples_dir: Path


class MarketConfig(BaseModel):
    qdrant_url: str
    collection: str
    originality_tau: float
    top_k: int
    corpus_limit: int
    sparse_model: str


class Config(BaseModel):
    llm: LLMConfig
    limits: Limits
    pipeline: PipelineConfig
    ocr: OCRConfig
    server: ServerConfig
    paths: Paths
    market: MarketConfig

    def path(self, p: Path) -> Path:
        return p if p.is_absolute() else ROOT / p


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    bsa_api_key: str = Field(default="")
    youtube_api_key: str = Field(default="")
    tmdb_api_key: str = Field(default="")
    bsa_contact: str = Field(default="")


@lru_cache
def get_config(path: str | None = None) -> Config:
    raw: dict[str, Any] = yaml.safe_load((Path(path) if path else ROOT / "config.yaml").read_text())
    return Config.model_validate(raw)


@lru_cache
def get_secrets() -> Secrets:
    return Secrets()
