"""Prepare and mutate real PostgreSQL/MySQL browser-certification sources."""

from __future__ import annotations

import argparse
import json
import os


def _connection(connector: str):
    password = os.environ["STEP3B_DB_PASSWORD"]
    if connector == "postgresql":
        import psycopg2

        return psycopg2.connect(
            host="127.0.0.1",
            port=int(os.environ["STEP3B_POSTGRES_PORT"]),
            dbname="knowledge",
            user="step3b",
            password=password,
        )
    import pymysql

    return pymysql.connect(
        host="127.0.0.1",
        port=int(os.environ["STEP3B_MYSQL_PORT"]),
        database="knowledge",
        user="step3b",
        password=password,
        autocommit=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=("initialize", "update", "schema", "versions")
    )
    arguments = parser.parse_args()
    versions: dict[str, str] = {}
    for connector in ("postgresql", "mysql"):
        connection = _connection(connector)
        try:
            with connection.cursor() as cursor:
                if arguments.action == "versions":
                    cursor.execute(
                        "SELECT version()"
                        if connector == "postgresql"
                        else "SELECT VERSION()"
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise RuntimeError(f"{connector} did not return its version")
                    versions[connector] = str(row[0])
                elif arguments.action == "initialize":
                    cursor.execute("DROP TABLE IF EXISTS step3b_browser_orders")
                    cursor.execute(
                        "CREATE TABLE step3b_browser_orders "
                        "(order_id VARCHAR(32) PRIMARY KEY, amount INTEGER NOT NULL)"
                    )
                    cursor.execute(
                        "INSERT INTO step3b_browser_orders(order_id, amount) "
                        "VALUES ('A-1', 12), ('B-2', 5)"
                    )
                elif arguments.action == "update":
                    cursor.execute(
                        "UPDATE step3b_browser_orders SET amount = 14 "
                        "WHERE order_id = 'A-1'"
                    )
                else:
                    cursor.execute(
                        "ALTER TABLE step3b_browser_orders "
                        "ADD COLUMN browser_note VARCHAR(64)"
                    )
            connection.commit()
        finally:
            connection.close()
    if versions:
        print(json.dumps(versions, sort_keys=True))


if __name__ == "__main__":
    main()
