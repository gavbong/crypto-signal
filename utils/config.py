import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

_ROOT = Path(__file__).parent.parent
_cfg: dict | None = None


def get() -> dict:
    global _cfg
    if _cfg is None:
        with open(_ROOT / "config.yaml") as f:
            _cfg = yaml.safe_load(f)
    return _cfg


def env(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return val


def db_path() -> Path:
    return _ROOT / "signals.db"
