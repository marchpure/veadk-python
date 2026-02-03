'''
Author: haoxingjun
Date: 2026-02-04 01:46:24
Email: haoxingjun@bytedance.com
LastEditors: haoxingjun
LastEditTime: 2026-02-04 01:46:56
Description: file information
Company: ByteDance
'''
import json
from pathlib import Path
import yaml


def load_config(config_path: str | None = None) -> dict:
    path = Path(config_path) if config_path else Path(__file__).resolve().parents[1] / "config" / "config.yaml"
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8")
    data = json.loads(content)
    if isinstance(data, list):
        return data
    return []


def read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8").strip()
    return content or None
