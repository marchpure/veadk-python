from pathlib import Path
import yaml

from intent_and_sql_tools.data_agent_tool.vanna_bridge import SQLVanna

_hands = None
_config_path = None


def init_engine(config_path: str | None = None):
    global _hands, _config_path
    _config_path = config_path
    _hands = None


def _load_config() -> dict:
    if _config_path:
        path = Path(_config_path)
    else:
        path = Path(__file__).resolve().parents[1] / "config" / "config.yaml"
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_hands() -> SQLVanna:
    global _hands
    if _hands is None:
        cfg = _load_config()
        _hands = SQLVanna(cfg["sql_engine"])
    return _hands
