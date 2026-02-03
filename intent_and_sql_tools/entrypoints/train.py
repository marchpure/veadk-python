import argparse

from intent_and_sql_tools.data_agent_tool.train import train_data_agent
from intent_and_sql_tools.intent_tool.train import train_intent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["intent", "sql", "all"])
    parser.add_argument("--config", default=None)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--brain-doc-file", default=None)
    parser.add_argument("--brain-samples-file", default=None)
    parser.add_argument("--hands-ddl-file", default=None)
    parser.add_argument("--hands-doc-file", default=None)
    parser.add_argument("--hands-samples-file", default=None)
    parser.add_argument("--hands-sql-file", default=None)
    parser.add_argument("--mock", action="store_true")
    args = parser.parse_args()

    if args.mode == "intent":
        train_intent(
            config_path=args.config,
            data_dir=args.data_dir,
            doc_file=args.brain_doc_file,
            samples_file=args.brain_samples_file,
            use_mock=args.mock,
        )
    elif args.mode == "sql":
        train_data_agent(
            config_path=args.config,
            data_dir=args.data_dir,
            ddl_file=args.hands_ddl_file,
            doc_file=args.hands_doc_file,
            samples_file=args.hands_samples_file,
            sql_file=args.hands_sql_file,
            use_mock=args.mock,
        )
    else:
        train_intent(
            config_path=args.config,
            data_dir=args.data_dir,
            doc_file=args.brain_doc_file,
            samples_file=args.brain_samples_file,
            use_mock=args.mock,
        )
        train_data_agent(
            config_path=args.config,
            data_dir=args.data_dir,
            ddl_file=args.hands_ddl_file,
            doc_file=args.hands_doc_file,
            samples_file=args.hands_samples_file,
            sql_file=args.hands_sql_file,
            use_mock=args.mock,
        )


if __name__ == "__main__":
    main()
