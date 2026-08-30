from .compat import knowledge_source_refs


def test_legacy_refs_are_deduplicated_in_stable_order() -> None:
    refs = knowledge_source_refs(
        {
            "openviking_profile_ids": ["p1", "p1", "p2"],
            "openviking_resource_refs": ["r1", "r1"],
        }
    )
    assert [(item.profile_ref, item.resource_ref) for item in refs] == [
        ("p1", None),
        ("p2", None),
        (None, "r1"),
    ]
