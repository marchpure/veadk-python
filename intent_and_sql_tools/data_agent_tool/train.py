'''
Author: haoxingjun
Date: 2026-02-04 01:31:17
Email: haoxingjun@bytedance.com
LastEditors: haoxingjun
LastEditTime: 2026-02-04 01:42:52
Description: file information
Company: ByteDance
'''
import argparse
import json
from pathlib import Path

from intent_and_sql_tools.common.vanna_base import MockVannaImpl
from intent_and_sql_tools.data_agent_tool.vanna_bridge import SQLVanna
from intent_and_sql_tools.common.train_utils import load_config, read_lines, read_json, read_text


def train_data_agent(
    config_path: str | None = None,
    data_dir: str | None = None,
    ddl_file: str | None = None,
    doc_file: str | None = None,
    samples_file: str | None = None,
    sql_file: str | None = None,
    use_mock: bool = False,
):
    cfg = load_config(config_path)
    hands = SQLVanna(cfg["sql_engine"], impl=MockVannaImpl() if use_mock else None)
    base_dir = Path(data_dir) if data_dir else Path(__file__).resolve().parents[1]
    ddl_path = Path(ddl_file) if ddl_file else base_dir / "ddl.sql"
    glossary_path = Path(doc_file) if doc_file else base_dir / "glossary.txt"
    samples_path = Path(samples_file) if samples_file else base_dir / "samples.json"
    sql_path = Path(sql_file) if sql_file else None

    ddl = read_text(ddl_path) or "CREATE TABLE user_stats (user_id INT, revenue DOUBLE, dt STRING)"
    definitions = read_lines(glossary_path) or ["指标：ARPU = revenue / users"]
    samples = read_json(samples_path) or [
        {"q": "查总营收", "sql": "SELECT sum(revenue) FROM user_stats"},
        {"q": "按天看营收", "sql": "SELECT dt, sum(revenue) FROM user_stats GROUP BY dt"},
    ]
    if sql_path and sql_path.exists():
        extra_sqls = read_lines(sql_path)
        for i, s in enumerate(extra_sqls, start=1):
            samples.append({"q": f"SQL_{i}", "sql": s})

    write_count = 0
    sample_count = 0
    hands.train(ddl=ddl)
    write_count += 1
    for doc in definitions:
        hands.train(documentation=doc)
        write_count += 1
    for item in samples:
        hands.train(question=item["q"], sql=item["sql"])
        sample_count += 1
        write_count += 1
    summary = {"pipeline": "data_agent", "write_count": write_count, "sample_count": sample_count}
    print(json.dumps(summary, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--ddl-file", default=None)
    parser.add_argument("--doc-file", default=None)
    parser.add_argument("--samples-file", default=None)
    parser.add_argument("--sql-file", default=None)
    parser.add_argument("--mock", action="store_true")
    args = parser.parse_args()
    train_data_agent(
        config_path=args.config,
        data_dir=args.data_dir,
        ddl_file=args.ddl_file,
        doc_file=args.doc_file,
        samples_file=args.samples_file,
        sql_file=args.sql_file,
        use_mock=args.mock,
    )


if __name__ == "__main__":
    main()
