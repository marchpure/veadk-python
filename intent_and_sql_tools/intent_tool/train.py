import argparse
import json
from pathlib import Path

from intent_and_sql_tools.common.vanna_base import MockVannaImpl
from intent_and_sql_tools.intent_tool.intent_tool import IntentVanna
from intent_and_sql_tools.common.train_utils import load_config, read_lines, read_json


def train_intent(
    config_path: str | None = None,
    data_dir: str | None = None,
    doc_file: str | None = None,
    samples_file: str | None = None,
    use_mock: bool = False,
):
    cfg = load_config(config_path)
    brain = IntentVanna(cfg["intent_engine"], impl=MockVannaImpl() if use_mock else None)
    base_dir = Path(data_dir) if data_dir else Path(__file__).resolve().parents[1]
    glossary_path = Path(doc_file) if doc_file else base_dir / "glossary.txt"
    samples_path = Path(samples_file) if samples_file else base_dir / "samples.json"

    glossary = read_lines(glossary_path) or [
        "术语：'土豪' = user_level >= 5",
        "术语：'流失' = is_active = 0",
        "术语：'MA多头' = close > ma5 > ma10",
    ]
    samples = read_json(samples_path) or [
        {
            "q": "查一下土豪流失",
            "json": {"intent": "query_metric", "payload": {"filters": ["level>=5"]}},
        },
        {
            "q": "选出MA多头的票",
            "json": {"intent": "screening", "payload": {"factors": ["ma_bull"]}},
        },
        {
            "q": "画个最近营收的图",
            "json": {"intent": "plot_chart", "payload": {"metric": "revenue"}},
        },
    ]

    doc_count = 0
    sample_count = 0
    for term in glossary:
        brain.train(documentation=term)
        doc_count += 1
    for item in samples:
        brain.train(question=item["q"], sql=json.dumps(item["json"], ensure_ascii=False))
        sample_count += 1
    summary = {"pipeline": "intent", "write_count": doc_count + sample_count, "sample_count": sample_count}
    print(json.dumps(summary, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--doc-file", default=None)
    parser.add_argument("--samples-file", default=None)
    parser.add_argument("--mock", action="store_true")
    args = parser.parse_args()
    train_intent(
        config_path=args.config,
        data_dir=args.data_dir,
        doc_file=args.doc_file,
        samples_file=args.samples_file,
        use_mock=args.mock,
    )


if __name__ == "__main__":
    main()
