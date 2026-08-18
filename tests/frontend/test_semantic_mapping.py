from __future__ import annotations

from frontend.server.knowledge_assets.semantic_mapping import (
    schema_to_semantic_seed,
    seed_to_agentkit_semantic_model_payload,
    seed_to_dashboard_manifest,
    validate_dashboard_manifest,
    validate_semantic_payload,
)


def _sales_schema() -> dict[str, object]:
    return {
        "domain": "sales",
        "tables": [
            {
                "name": "sales_order",
                "columns": [
                    {"name": "order_id", "type": "integer", "primary_key": True},
                    {"name": "store_id", "type": "integer"},
                    {"name": "sell_date", "type": "date"},
                    {"name": "amount", "type": "decimal"},
                    {"name": "customer_phone", "type": "varchar"},
                    {"name": "status", "type": "varchar"},
                ],
            },
            {
                "name": "store",
                "columns": [
                    {"name": "store_id", "type": "integer", "primary_key": True},
                    {"name": "store_name", "type": "varchar"},
                    {"name": "region", "type": "varchar"},
                ],
            },
            {
                "name": "order_tag",
                "columns": [
                    {"name": "order_id", "type": "integer"},
                    {"name": "tag_id", "type": "integer"},
                ],
            },
            {
                "name": "tag",
                "columns": [
                    {"name": "tag_id", "type": "integer", "primary_key": True},
                    {"name": "tag_name", "type": "varchar"},
                ],
            },
        ],
        "foreign_keys": [
            {
                "table": "sales_order",
                "referred_table": "store",
                "constrained_columns": ["store_id"],
                "referred_columns": ["store_id"],
            },
            {
                "table": "order_tag",
                "referred_table": "sales_order",
                "constrained_columns": ["order_id"],
                "referred_columns": ["order_id"],
            },
            {
                "table": "order_tag",
                "referred_table": "tag",
                "constrained_columns": ["tag_id"],
                "referred_columns": ["tag_id"],
            },
        ],
        "freshness": {"snapshot_id": "snap-sales", "data_through": "2026-08-15"},
    }


def test_schema_to_semantic_seed_maps_entities_relationships_metrics_and_policies() -> None:
    seed = schema_to_semantic_seed(
        _sales_schema(),
        {"sample_mode": "schema_only", "tables": {"sales_order": {"row_count": 20}}},
        target_domain="sales",
    )

    assert {entity.id for entity in seed.entities} == {"sales_order", "store", "tag"}
    assert "order_tag" not in {entity.id for entity in seed.entities}
    assert any(rel.cardinality == "many-to-many" for rel in seed.relationships)
    assert any(metric.id == "sales_order_amount_sum" for metric in seed.candidate_metrics)
    assert any(dim.id == "sales_order_sell_date" and dim.kind == "time" for dim in seed.candidate_dimensions)
    assert {"entity": "sales_order", "field": "customer_phone"} in seed.policies["denied_fields"]
    assert all("customer_phone" not in metric.formula for metric in seed.candidate_metrics)
    assert seed.freshness["snapshot_id"] == "snap-sales"


def test_seed_payload_and_dashboard_manifest_validate_without_raw_sql() -> None:
    seed = schema_to_semantic_seed(_sales_schema(), target_domain="sales")
    semantic = seed_to_agentkit_semantic_model_payload(seed)
    manifest = seed_to_dashboard_manifest(seed, semantic["mdl"]["model"]["slug"], "sales overview")

    assert semantic["runtime"]["direct_database_access"] is False
    assert semantic["governance"]["raw_sql_fallback"] is False
    assert semantic["runtime"]["query_url"].startswith("/api/knowledge-assets/assets/semantic_model/")
    assert validate_semantic_payload(semantic) == []
    assert manifest["schema"] == "agentkit.dashboard.manifest.v1"
    assert manifest["tiles"]
    assert validate_dashboard_manifest(manifest, semantic) == []
