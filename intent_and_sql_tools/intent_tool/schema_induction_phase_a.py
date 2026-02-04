import argparse

from intent_and_sql_tools.intent_tool.nl2json_pipeline.train.config import (
    load_config,
    merge_phase_a_overrides,
)
from intent_and_sql_tools.intent_tool.nl2json_pipeline.train.schema_induction.phase_a import (
    run_schema_induction_phase_a,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    cfg = merge_phase_a_overrides(cfg, output_path=args.output, batch_size=args.batch_size)
    run_schema_induction_phase_a(cfg)


if __name__ == "__main__":
    main()
