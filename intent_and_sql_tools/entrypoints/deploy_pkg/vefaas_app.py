from pathlib import Path
import sys

root = Path(__file__).resolve().parent
python_dir = root / "python"
sys.path.insert(0, str(root))
if python_dir.exists():
    sys.path.insert(0, str(python_dir))

from intent_and_sql_tools.entrypoints.intent_api import app

# veFaaS 入口文件，直接导入现有的 FastAPI 应用
