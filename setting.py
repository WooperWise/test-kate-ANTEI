"""Central settings entry point.

Loads and merges, in order of increasing priority:
  1. harness.yaml (root)          - model, budgets, paths
  2. config/*.yaml                - queries, sources, logging
  3. .env / environment variables - secrets and endpoint overrides (highest priority)
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")


def _resolve_env(value: Any) -> Any:
    """Expand ${VAR:default} placeholders using environment variables."""
    if isinstance(value, str):

        def repl(match: re.Match[str]) -> str:
            var, default = match.group(1), match.group(2)
            return os.environ.get(var, default if default is not None else match.group(0))

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return _resolve_env(yaml.safe_load(fh) or {})


class Secrets(BaseSettings):
    """Secrets and endpoint overrides from .env / environment (highest priority)."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    mito_model: str | None = Field(default=None, alias="MITO_MODEL")
    ncbi_api_key: str | None = Field(default=None, alias="NCBI_API_KEY")


class ModelConfig(BaseModel):
    base_url: str
    name: str
    temperature: float = 0.2


class LimitsConfig(BaseModel):
    max_plan_steps: int = 12
    max_review_iterations: int = 3
    max_records: int = 30
    llm_concurrency: int = 4
    wall_clock_minutes: int = 15
    max_tokens_per_run: int = 400_000


class PathsConfig(BaseModel):
    skills_dir: Path
    cache_dir: Path
    outputs_dir: Path
    queries: Path
    sources: Path


class LoggingConsole(BaseModel):
    enabled: bool = True
    format: str = "{ts} [{event}] {agent} {tool} {detail}"


class LoggingJsonl(BaseModel):
    enabled: bool = True
    filename_pattern: str = "run_{run_id}.jsonl"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    console: LoggingConsole = LoggingConsole()
    jsonl: LoggingJsonl = LoggingJsonl()


class HttpSource(BaseModel):
    base_url: str
    timeout_seconds: float = 20
    retries: int = 3
    retry_backoff_seconds: float = 1.5
    rate_limit_seconds: float = 0.0


class PubMedSource(HttpSource):
    search: str = "esearch.fcgi"
    fetch: str = "efetch.fcgi"
    db: str = "pubmed"
    retmode: str = "json"
    rate_limit_seconds: float = 0.4


class EuropePmcSource(HttpSource):
    search: str = "search"
    format: str = "json"
    result_type: str = "core"


class SourcesConfig(BaseModel):
    pubmed: PubMedSource = PubMedSource(base_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils")
    europepmc: EuropePmcSource = EuropePmcSource(base_url="https://www.ebi.ac.uk/europepmc/webservices/rest")
    ctgov: HttpSource = HttpSource(base_url="https://clinicaltrials.gov/api/v2/studies")


class Settings(BaseModel):
    """Fully merged, effective configuration for one run."""

    model: ModelConfig
    limits: LimitsConfig
    paths: PathsConfig
    logging: LoggingConfig
    sources: SourcesConfig
    queries_config: dict[str, Any]
    api_key: str = "dummy"
    ncbi_api_key: str | None = None

    @property
    def root(self) -> Path:
        return ROOT


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build the effective settings; cached for the process lifetime."""
    secrets = Secrets()
    main = _load_yaml(ROOT / "harness.yaml")

    model_raw = main.get("model", {})
    model = ModelConfig(
        base_url=secrets.openai_base_url or model_raw["base_url"],
        name=secrets.mito_model or model_raw["name"],
        temperature=float(model_raw.get("temperature", 0.2)),
    )
    limits = LimitsConfig(**main.get("limits", {}))

    paths_raw = main.get("paths", {})
    paths = PathsConfig(
        skills_dir=ROOT / paths_raw.get("skills_dir", "skills"),
        cache_dir=ROOT / paths_raw.get("cache_dir", "data/cache"),
        outputs_dir=ROOT / paths_raw.get("outputs_dir", "outputs"),
        queries=ROOT / paths_raw.get("queries", "config/queries.yaml"),
        sources=ROOT / paths_raw.get("sources", "config/sources.yaml"),
    )

    logging_cfg = LoggingConfig(**_load_yaml(paths.sources.parent / "logging.yaml").get("logging", {}))
    sources_cfg = SourcesConfig(**_load_yaml(paths.sources).get("sources", {}))
    queries_cfg = _load_yaml(paths.queries)

    return Settings(
        model=model,
        limits=limits,
        paths=paths,
        logging=logging_cfg,
        sources=sources_cfg,
        queries_config=queries_cfg,
        api_key=secrets.openai_api_key or "dummy",
        ncbi_api_key=secrets.ncbi_api_key,
    )
