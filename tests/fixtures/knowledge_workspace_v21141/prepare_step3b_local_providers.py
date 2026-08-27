"""Seed the session-owned MinIO, Redpanda and ClickHouse test services."""

from __future__ import annotations

import json
import os


def main() -> None:
    import boto3
    from clickhouse_connect import get_client
    from confluent_kafka import Producer
    from confluent_kafka.admin import AdminClient, NewTopic

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
    client.command("INSERT INTO knowledge.step3b_events VALUES ('CH-1', 9)")
    client.close()
    print(
        json.dumps(
            {"s3": bucket, "kafka": topic, "clickhouse": "knowledge.step3b_events"}
        )
    )


if __name__ == "__main__":
    main()
