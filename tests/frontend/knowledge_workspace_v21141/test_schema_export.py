from frontend.server.knowledge_assets.schema_export import _render_typescript


def test_schema_export_uses_type_alias_for_unconstrained_definition() -> None:
    rendered = _render_typescript(
        {
            "$defs": {
                "JsonValue": {},
            }
        }
    )

    assert "export type JsonValue = unknown;" in rendered
    assert "export interface JsonValue unknown" not in rendered
