"""Template-driven SkillDraft builder and typed conversational patch service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contract_base import ContextRevisionRef, SkillManifest, TemplateRef
from .contract_data import SkillDraftRevision
from .template_registry import SqliteTemplateRegistry, template_digest


@dataclass(frozen=True)
class SkillRevisionDiff:
    from_revision: int
    to_revision: int
    changed_paths: tuple[str, ...]


class TemplateSkillBuilder:
    def __init__(self, registry: SqliteTemplateRegistry) -> None:
        self.registry = registry

    def build(
        self,
        *,
        workspace_id: str,
        manifest: SkillManifest,
        selected_template: TemplateRef,
        context_revision_refs: list[ContextRevisionRef],
        created_at: str,
    ) -> SkillDraftRevision:
        template = self.registry.get(
            selected_template.template_id, selected_template.version, workspace_id
        )
        if template is None or template_digest(template) != selected_template.digest:
            raise ValueError(
                "TemplateRef does not resolve to an immutable TemplateSpec"
            )
        if manifest.spec.kind != template.capability_intent:
            raise ValueError(
                "Skill kind must be selected by TemplateSpec capabilityIntent"
            )
        available_context = {item.kind for item in context_revision_refs}
        aliases = {
            "tabular": {"golden_asset", "source"},
            "document": {"document", "golden_asset"},
            "semantic_skill": {"semantic_skill"},
            "knowledge": {"document", "golden_asset"},
            "graph": {"golden_asset"},
            "tool": {"tool"},
            "observation": {"golden_asset", "source"},
        }
        missing = [
            kind
            for kind in template.required_context_kinds
            if not (aliases[kind] & available_context)
        ]
        if missing:
            raise ValueError(f"Missing required context kinds: {', '.join(missing)}")
        bound = manifest.model_copy(
            update={
                "spec": manifest.spec.model_copy(
                    update={
                        "template_ref": selected_template,
                        "default_renderer": template.default_renderer,
                        "context_revision_refs": context_revision_refs,
                    }
                )
            }
        )
        return SkillDraftRevision(
            id=f"{manifest.metadata.id}:1",
            skill_id=manifest.metadata.id,
            revision=1,
            manifest=bound,
            source_revision_refs=[
                item.revision_id
                for item in context_revision_refs
                if item.kind in {"source", "document"}
            ],
            golden_asset_revision_refs=[
                item.revision_id
                for item in context_revision_refs
                if item.kind == "golden_asset"
            ],
            template_ref=selected_template,
            context_revision_refs=context_revision_refs,
            created_at=created_at,
        )

    def patch(
        self,
        draft: SkillDraftRevision,
        *,
        changes: dict[str, Any],
        created_at: str,
    ) -> tuple[SkillDraftRevision, SkillRevisionDiff]:
        """Apply an allow-listed typed patch; BuildPlan is never public state."""

        prefixes = {
            "analysis": (
                "kindSpec.question",
                "kindSpec.queryPlanRef",
                "kindSpec.dashboard.title",
                "kindSpec.dashboard.kpiLabels",
                "kindSpec.dashboard.chartTitle",
                "kindSpec.dashboard.filterFields",
                "kindSpec.dashboard.drillFields",
            ),
            "semantic": (
                "kindSpec.metricRefs",
                "kindSpec.dimensionRefs",
                "kindSpec.relationshipRefs",
            ),
            "sop": ("kindSpec.steps",),
            "graph_ontology": (
                "kindSpec.constraintRefs",
                "kindSpec.entities",
                "kindSpec.relationships",
            ),
        }
        allowed = prefixes.get(draft.manifest.spec.kind, ())
        rejected = sorted(path for path in changes if not path.startswith(allowed))
        if rejected:
            raise ValueError(
                f"Unsupported conversational patch paths: {', '.join(rejected)}"
            )
        spec_data = draft.manifest.spec.kind_spec.model_dump(mode="python")
        for path, value in changes.items():
            segments = _snake_segments(path.removeprefix("kindSpec."))
            _set_path(spec_data, segments, value)
        kind_spec_type = type(draft.manifest.spec.kind_spec)
        revised_kind_spec = kind_spec_type.model_validate(spec_data)
        revision = draft.revision + 1
        manifest = draft.manifest.model_copy(
            update={
                "metadata": draft.manifest.metadata.model_copy(
                    update={"version": f"1.0.{revision - 1}"}
                ),
                "spec": draft.manifest.spec.model_copy(
                    update={"kind_spec": revised_kind_spec}
                ),
            }
        )
        revised = draft.model_copy(
            update={
                "id": f"{draft.skill_id}:{revision}",
                "revision": revision,
                "manifest": manifest,
                "status": "draft",
                "created_at": created_at,
            }
        )
        return revised, SkillRevisionDiff(
            from_revision=draft.revision,
            to_revision=revision,
            changed_paths=tuple(sorted(changes)),
        )


def _snake_segments(path: str) -> list[str | int]:
    import re

    result: list[str | int] = []
    for token in path.split("."):
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9]*)(?:\[(\d+)\])?", token)
        if not match:
            raise ValueError(f"Invalid patch path: {path}")
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", match.group(1)).lower()
        result.append(name)
        if match.group(2) is not None:
            result.append(int(match.group(2)))
    return result


def _set_path(target: Any, segments: list[str | int], value: Any) -> None:
    cursor = target
    for segment in segments[:-1]:
        cursor = cursor[segment]
    cursor[segments[-1]] = value
