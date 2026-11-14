"""Configuration: config.toml at the repo root, overridden by OA_<KEY> environment variables."""

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    db_path: Path = ROOT / "data" / "index.db"
    manuals_dir: Path = ROOT / "manuals"
    top_k: int = 3
    min_score: float = 2.5
    llm_url: str = "http://127.0.0.1:18181"
    llm_model: str = "LiquidAI/LFM3-1.7B-GGUF:Q4_0"
    llm_mock: bool = False
    llm_max_tokens: int = 200
    llm_timeout_s: float = 60
    page_chars: int = 2500
    embed_url: str = "http://127.0.0.1:18182"
    embed_model: str = "LFM2.5-Embedding-350M"


def _coerce(value, typ):
    if typ is bool and isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if typ is Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else ROOT / path
    return typ(value)


def load_config(path: Path | None = None) -> Config:
    path = Path(os.environ.get("OA_CONFIG", path or ROOT / "config.toml"))
    values = {}
    if path.exists():
        with path.open("rb") as f:
            values.update(tomllib.load(f))
    for f in fields(Config):
        env = os.environ.get(f"OA_{f.name.upper()}")
        if env is not None:
            values[f.name] = env
    types = {f.name: type(f.default) if not isinstance(f.default, Path) else Path for f in fields(Config)}
    return Config(**{k: _coerce(v, types[k]) for k, v in values.items() if k in types})
