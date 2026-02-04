import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from intent_and_sql_tools.data_agent_tool.train import train_data_agent
from intent_and_sql_tools.intent_tool.train import train_intent, train_schema_induction_phase_a
from intent_and_sql_tools.intent_tool.nl2json_pipeline.train.config import (
    ArkConfig,
    TermFieldMapping,
    TermSourceConfig,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["intent", "sql", "all", "schema_phase_a"])
    parser.add_argument("--config", default=None)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--brain-doc-file", default=None)
    parser.add_argument("--brain-samples-file", default=None)
    parser.add_argument("--brain-term-source", default=None)
    parser.add_argument("--brain-term-format", default=None)
    parser.add_argument("--brain-term-id-field", default="term_id")
    parser.add_argument("--brain-term-name-field", default="name")
    parser.add_argument("--brain-term-aliases-field", default="aliases")
    parser.add_argument("--brain-term-desc-field", default="desc")
    parser.add_argument("--brain-term-csv-delimiter", default=",")
    parser.add_argument("--brain-term-alias-delimiter", default=",")
    parser.add_argument("--brain-fewshot-file", default=None)
    parser.add_argument("--brain-fewshot-format", default=None)
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
    parser.add_argument("--hands-ddl-file", default=None)
    parser.add_argument("--hands-doc-file", default=None)
    parser.add_argument("--hands-samples-file", default=None)
    parser.add_argument("--hands-sql-file", default=None)
    parser.add_argument("--mock", action="store_true")
    args = parser.parse_args()
    print(f"[train] mode={args.mode}")

    term_source = None
    if args.brain_term_source:
        term_source = TermSourceConfig(
            path=args.brain_term_source,
            format=args.brain_term_format,
            field_mapping=TermFieldMapping(
                term_id=args.brain_term_id_field,
                name=args.brain_term_name_field,
                aliases=args.brain_term_aliases_field,
                desc=args.brain_term_desc_field,
            ),
            csv_delimiter=args.brain_term_csv_delimiter,
            alias_delimiter=args.brain_term_alias_delimiter,
        )
        print(f"[train] term_source={term_source.path} format={term_source.format}")
    if args.mode == "intent":
        print("[train] start intent training")
        train_intent(
            config_path=args.config,
            data_dir=args.data_dir,
            doc_file=args.brain_doc_file,
            samples_file=args.brain_samples_file,
            term_source=term_source,
            fewshot_path=args.brain_fewshot_file,
            fewshot_format=args.brain_fewshot_format,
            use_mock=args.mock,
        )
        print("[train] intent training done")
    elif args.mode == "sql":
        print("[train] start sql training")
        train_data_agent(
            config_path=args.config,
            data_dir=args.data_dir,
            ddl_file=args.hands_ddl_file,
            doc_file=args.hands_doc_file,
            samples_file=args.hands_samples_file,
            sql_file=args.hands_sql_file,
            use_mock=args.mock,
        )
        print("[train] sql training done")
    else:
        if args.mode == "schema_phase_a":
            if term_source is None:
                raise ValueError("schema_phase_a requires --brain-term-source")
            print("[train] start schema_phase_a induction")
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
            print("[train] schema_phase_a induction done")
            return
        print("[train] start intent training")
        train_intent(
            config_path=args.config,
            data_dir=args.data_dir,
            doc_file=args.brain_doc_file,
            samples_file=args.brain_samples_file,
            term_source=term_source,
            fewshot_path=args.brain_fewshot_file,
            fewshot_format=args.brain_fewshot_format,
            use_mock=args.mock,
        )
        print("[train] intent training done")
        print("[train] start sql training")
        train_data_agent(
            config_path=args.config,
            data_dir=args.data_dir,
            ddl_file=args.hands_ddl_file,
            doc_file=args.hands_doc_file,
            samples_file=args.hands_samples_file,
            sql_file=args.hands_sql_file,
            use_mock=args.mock,
        )
        print("[train] sql training done")


if __name__ == "__main__":
    main()
