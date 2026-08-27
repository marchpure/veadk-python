"""Seed the session-owned local provider test services."""

from __future__ import annotations

import json
import os


def main() -> None:
    import boto3
    from clickhouse_connect import get_client
    from confluent_kafka import Producer
    from confluent_kafka.admin import AdminClient, NewTopic
    import oracledb

    selected = {
        item.strip()
        for item in os.environ.get(
            "STEP3B_BROWSER_PROVIDER_CONNECTORS",
            "s3,kafka,clickhouse,oracle,sqlserver,starrocks,doris,hive",
        ).split(",")
        if item.strip()
    }

    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ.get("STEP3B_MINIO_ENDPOINT", "http://127.0.0.1:26344"),
        aws_access_key_id=os.environ.get("STEP3B_MINIO_ACCESS_KEY", "step3badmin"),
        aws_secret_access_key=os.environ.get(
            "STEP3B_MINIO_SECRET_KEY", "step3bpassword"
        ),
        region_name="us-east-1",
    )
    bucket = "step3b-r9"
    if "s3" in selected:
        try:
            s3.create_bucket(Bucket=bucket)
        except Exception as error:
            if "BucketAlreadyOwnedByYou" not in str(error):
                raise
        s3.put_object(
            Bucket=bucket,
            Key="golden/orders.json",
            Body=b'{"order_id":"S3-1","amount":42}\n',
            ContentType="application/json",
        )

    bootstrap = os.environ.get("STEP3B_KAFKA_BOOTSTRAP", "127.0.0.1:26346")
    admin = AdminClient({"bootstrap.servers": bootstrap})
    topic = "step3b-events"
    if "kafka" in selected:
        result = admin.create_topics(
            [NewTopic(topic, num_partitions=1, replication_factor=1)]
        )[topic]
        try:
            result.result()
        except Exception as error:
            if "TOPIC_ALREADY_EXISTS" not in str(error):
                raise
        producer = Producer({"bootstrap.servers": bootstrap})
        producer.produce(
            topic,
            key="evt-1",
            value=json.dumps({"event_id": "K-1", "amount": 7}).encode(),
        )
        producer.flush()

    client = get_client(
        host="127.0.0.1",
        port=int(os.environ.get("STEP3B_CLICKHOUSE_HTTP_PORT", "26350")),
        username=os.environ.get("STEP3B_CLICKHOUSE_USER", "step3b"),
        password=os.environ.get("STEP3B_CLICKHOUSE_PASSWORD", "step3bpassword"),
        database="default",
    )
    if "clickhouse" in selected:
        client.command("INSERT INTO knowledge.step3b_events VALUES ('CH-1', 9)")
    client.close()
    oracle = oracledb.connect(
        user=os.environ.get("STEP3B_ORACLE_USER", "step3b"),
        password=os.environ.get("STEP3B_ORACLE_PASSWORD", "Step3bAppPassword1!"),
        dsn=os.environ.get("STEP3B_ORACLE_DSN", "127.0.0.1:26352/FREEPDB1"),
    )
    if "oracle" in selected:
        try:
            with oracle.cursor() as cursor:
                try:
                    cursor.execute("DROP TABLE step3b_orders PURGE")
                except oracledb.DatabaseError as error:
                    if "ORA-00942" not in str(error):
                        raise
                cursor.execute(
                    "CREATE TABLE step3b_orders "
                    "(order_id VARCHAR2(32) PRIMARY KEY, amount NUMBER NOT NULL)"
                )
                cursor.execute(
                    "INSERT INTO step3b_orders(order_id, amount) VALUES ('O-1', 17)"
                )
            oracle.commit()
        finally:
            oracle.close()
    import pyodbc
    import pymysql
    from pyhive import hive

    driver = os.environ.get(
        "STEP3B_SQLSERVER_ODBC_DRIVER", "/opt/homebrew/opt/freetds/lib/libtdsodbc.so"
    )
    sqlserver_connection = pyodbc.connect(
        "DRIVER={driver};SERVER=127.0.0.1;PORT=26353;DATABASE=knowledge;"
        "UID=sa;PWD=Step3bSqlPassword1!;TDS_Version=7.4;Encrypt=no;"
        "TrustServerCertificate=yes;".format(driver=driver),
        autocommit=True,
        timeout=10,
    )
    if "sqlserver" in selected:
        try:
            with sqlserver_connection.cursor() as cursor:
                cursor.execute(
                    "IF OBJECT_ID('dbo.step3b_orders', 'U') IS NOT NULL "
                    "DROP TABLE dbo.step3b_orders"
                )
                cursor.execute(
                    "CREATE TABLE dbo.step3b_orders "
                    "(order_id varchar(32) primary key, amount int not null)"
                )
                cursor.execute(
                    "INSERT INTO dbo.step3b_orders(order_id, amount) VALUES ('M-1', 23)"
                )
        finally:
            sqlserver_connection.close()
    starrocks_connection = pymysql.connect(
        host=os.environ.get("STEP3B_STARROCKS_HOST", "127.0.0.1"),
        port=int(os.environ.get("STEP3B_STARROCKS_PORT", "26354")),
        user=os.environ.get("STEP3B_STARROCKS_USER", "root"),
        password=os.environ["STEP3B_STARROCKS_PASSWORD"],
        database=os.environ.get("STEP3B_STARROCKS_DATABASE", "knowledge"),
        autocommit=True,
        connect_timeout=10,
    )
    if "starrocks" in selected:
        try:
            with starrocks_connection.cursor() as cursor:
                cursor.execute("DROP TABLE IF EXISTS step3b_starrocks_orders")
                cursor.execute(
                    "CREATE TABLE step3b_starrocks_orders "
                    "(order_id VARCHAR(32), amount INT) "
                    "DISTRIBUTED BY HASH(order_id) BUCKETS 1 "
                    "PROPERTIES ('replication_num' = '1')"
                )
                cursor.execute(
                    "INSERT INTO step3b_starrocks_orders(order_id, amount) "
                    "VALUES ('SR-1', 31), ('SR-2', 44)"
                )
        finally:
            starrocks_connection.close()
    doris_connection = pymysql.connect(
        host=os.environ.get("STEP3B_DORIS_HOST", "127.0.0.1"),
        port=int(os.environ.get("STEP3B_DORIS_PORT", "26359")),
        user=os.environ.get("STEP3B_DORIS_USER", "step3b"),
        password=os.environ.get("STEP3B_DORIS_PASSWORD", "Step3bDorisPassword1!"),
        database=os.environ.get("STEP3B_DORIS_DATABASE", "knowledge"),
        autocommit=True,
        connect_timeout=10,
    )
    if "doris" in selected:
        try:
            with doris_connection.cursor() as cursor:
                # The browser BFF deliberately uses a read-only Doris secret. The
                # table is provisioned by the session-owned target bootstrap; the
                # seed step must not escalate that secret into DDL/DML.
                cursor.execute(
                    "SELECT order_id, amount FROM step3b_doris_orders "
                    "ORDER BY order_id LIMIT 2"
                )
                rows = cursor.fetchall()
                if len(rows) < 1:
                    raise RuntimeError(
                        "Doris seed table is empty; provision it with an administrator "
                        "before running browser evidence."
                    )
        finally:
            doris_connection.close()
    hive_connection = hive.connect(
        host=os.environ.get("STEP3B_HIVE_HOST", "127.0.0.1"),
        port=int(os.environ.get("STEP3B_HIVE_PORT", "26363")),
        username=os.environ.get("STEP3B_HIVE_USER", "step3b"),
        auth=os.environ.get("STEP3B_HIVE_AUTH", "NONE"),
        database=os.environ.get("STEP3B_HIVE_DATABASE", "knowledge"),
    )
    if "hive" in selected:
        try:
            with hive_connection.cursor() as cursor:
                cursor.execute(
                    "SELECT order_id, amount FROM knowledge.step3b_hive_orders "
                    "ORDER BY order_id LIMIT 2"
                )
                rows = cursor.fetchall()
                if len(rows) < 1:
                    raise RuntimeError(
                        "Hive seed table is empty; provision it with an administrator "
                        "before running browser evidence."
                    )
        finally:
            hive_connection.close()
    print(
        json.dumps(
            {
                "s3": bucket,
                "kafka": topic,
                "clickhouse": "knowledge.step3b_events",
                "oracle": "STEP3B.STEP3B_ORDERS",
                "sqlserver": "dbo.step3b_orders",
        "starrocks": "knowledge.step3b_starrocks_orders",
        "doris": "knowledge.step3b_doris_orders",
            }
        )
    )


if __name__ == "__main__":
    main()
