import argparse
import json
from pathlib import Path

from intent_and_sql_tools.common.train_utils import load_config, read_lines, read_json
from intent_and_sql_tools.common.vanna_base import MockVannaImpl
from intent_and_sql_tools.intent_tool.intent_tool import IntentVanna
from intent_and_sql_tools.intent_tool.nl2json_pipeline.train.config import (
    ArkConfig,
    FewShotConfig,
    PipelineConfig,
    SchemaInductionPhaseAConfig,
    TermFieldMapping,
    TermSourceConfig,
)
from intent_and_sql_tools.intent_tool.nl2json_pipeline.train.io.fewshot_loader import (
    load_fewshot,
)
from intent_and_sql_tools.intent_tool.nl2json_pipeline.train.io.term_loader import (
    load_terms,
)
from intent_and_sql_tools.intent_tool.nl2json_pipeline.train.schema_induction.phase_a import (
    run_schema_induction_phase_a,
)

def train_intent(
    config_path: str | None = None,
    data_dir: str | None = None,
    doc_file: str | None = None,
    samples_file: str | None = None,
    term_source: TermSourceConfig | None = None,
    fewshot_path: str | None = None,
    fewshot_format: str | None = None,
    use_mock: bool = False,
):
    cfg = load_config(config_path)
    brain = IntentVanna(cfg["intent_engine"], impl=MockVannaImpl() if use_mock else None)
    base_dir = Path(data_dir) if data_dir else Path(__file__).resolve().parents[1]
    glossary_path = Path(doc_file) if doc_file else base_dir / "glossary.txt"
    samples_path = Path(samples_file) if samples_file else base_dir / "samples.json"
    glossary = _load_glossary(glossary_path, term_source)
    samples = _load_samples(samples_path, fewshot_path, fewshot_format)

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


def train_schema_induction_phase_a(
    term_source: TermSourceConfig,
    output_path: str | None = None,
    batch_size: int | None = None,
    min_slots: int = 8,
    max_slots: int = 15,
    max_batches: int | None = None,
    ark_config: ArkConfig | None = None,
):
    phase_a = SchemaInductionPhaseAConfig(
        batch_size=batch_size or 200,
        min_slots=min_slots,
        max_slots=max_slots,
        output_path=output_path,
        max_batches=max_batches,
    )
    config = PipelineConfig(
        term_source=term_source,
        llm=ark_config or ArkConfig(),
        schema_induction_phase_a=phase_a,
    )
    run_schema_induction_phase_a(config)


def _load_glossary(glossary_path: Path, term_source: TermSourceConfig | None) -> list[str]:
    if term_source:
        terms = load_terms(term_source)
        return [_format_term_doc(term) for term in terms]
    glossary = read_lines(glossary_path)
    if glossary:
        return glossary
    return [
        "术语：'土豪' = user_level >= 5",
        "术语：'流失' = is_active = 0",
        "术语：'MA多头' = close > ma5 > ma10",
    ]


def _load_samples(samples_path: Path, fewshot_path: str | None, fewshot_format: str | None) -> list[dict]:
    if fewshot_path:
        examples = load_fewshot(FewShotConfig(path=fewshot_path, format=fewshot_format))
        if examples:
            return [{"q": item.query, "json": item.ground_truth_json} for item in examples]
    if samples_path.suffix.lower() == ".csv":
        return []
    samples = read_json(samples_path)
    if samples:
        return samples
    return [
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


def _format_term_doc(term) -> str:
    alias_text = ", ".join(term.aliases) if term.aliases else ""
    if alias_text:
        return f"术语：{term.name} | 别名: {alias_text} | 描述: {term.desc}"
    return f"术语：{term.name} | 描述: {term.desc}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--doc-file", default=None)
    parser.add_argument("--samples-file", default=None)
    parser.add_argument("--term-source", default=None)
    parser.add_argument("--term-format", default=None)
    parser.add_argument("--term-id-field", default="term_id")
    parser.add_argument("--term-name-field", default="name")
    parser.add_argument("--term-aliases-field", default="aliases")
    parser.add_argument("--term-desc-field", default="desc")
    parser.add_argument("--term-csv-delimiter", default=",")
    parser.add_argument("--term-alias-delimiter", default=",")
    parser.add_argument("--fewshot-file", default=None)
    parser.add_argument("--fewshot-format", default=None)
    parser.add_argument("--schema-phase-a", action="store_true")
    parser.add_argument("--schema-output", default=None)
    parser.add_argument("--schema-batch-size", type=int, default=None)
    parser.add_argument("--schema-max-batches", type=int, default=None)
    parser.add_argument("--schema-min-slots", type=int, default=8)
    parser.add_argument("--schema-max-slots", type=int, default=15)
    parser.add_argument("--ark-api-key", default=None)
    parser.add_argument("--ark-api-base", default=None)
    parser.add_argument("--ark-model", default=None)
    parser.add_argument("--ark-timeout", type=float, default=60.0)
    parser.add_argument("--ark-max-retries", type=int, default=3)
    parser.add_argument("--mock", action="store_true")
    args = parser.parse_args()
    term_source = None
    if args.term_source:
        term_source = TermSourceConfig(
            path=args.term_source,
            format=args.term_format,
            field_mapping=TermFieldMapping(
                term_id=args.term_id_field,
                name=args.term_name_field,
                aliases=args.term_aliases_field,
                desc=args.term_desc_field,
            ),
            csv_delimiter=args.term_csv_delimiter,
            alias_delimiter=args.term_alias_delimiter,
        )
    if args.schema_phase_a:
        if term_source is None:
            raise ValueError("schema_phase_a requires --term-source")
        ark_config = ArkConfig(
            api_key=args.ark_api_key,
            api_base=args.ark_api_base,
            model=args.ark_model,
            timeout=args.ark_timeout,
            max_retries=args.ark_max_retries,
        )
        train_schema_induction_phase_a(
            term_source=term_source,
            output_path=args.schema_output,
            batch_size=args.schema_batch_size,
            min_slots=args.schema_min_slots,
            max_slots=args.schema_max_slots,
            max_batches=args.schema_max_batches,
            ark_config=ark_config,
        )
        return
    train_intent(
        config_path=args.config,
        data_dir=args.data_dir,
        doc_file=args.doc_file,
        samples_file=args.samples_file,
        term_source=term_source,
        fewshot_path=args.fewshot_file,
        fewshot_format=args.fewshot_format,
        use_mock=args.mock,
    )


if __name__ == "__main__":
    main()
