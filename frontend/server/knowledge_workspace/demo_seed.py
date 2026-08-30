"""Deterministic, offline demo Skill seed for the local Knowledge Workspace.

The seed is intentionally a versioned bundle, not an AutoSkill response.  It
uses the same repository objects and validators as the normal lifecycle, so
the resulting IDs are real and survive a BFF restart.
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
import zipfile
from pathlib import Path
from typing import Any

from .html_artifact import validate_html_artifact
from .models import (
    Artifact,
    AuthoringSession,
    Invocation,
    InvocationKind,
    InvocationStatus,
    Publication,
    SkillRevision,
    TemplateKey,
    WorkspaceResource,
    WorkspaceResourceKind,
    WorkspaceUpload,
)
from .service import Actor, KnowledgeWorkspaceService
from .zip_validator import validate_skill_zip

SEED_VERSION = "three-real-demo-skills-v1"
ROOT = Path(__file__).resolve().parents[3]

SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "id": "anta-operations",
        "name": "安踏经营日报",
        "directory": "anta-operations",
        "fixture": "anta-operations.csv",
        "template": TemplateKey.DASHBOARD,
        "kind": WorkspaceResourceKind.FILE,
        "goal": "按日期和门店展示订单量、GMV、客单价、退货率趋势和门店排行。",
        "html": "<h1>安踏经营日报</h1><p>GMV ¥493,450 · 订单量 694 · 客单价 ¥710.73</p><h2>门店排行</h2><ol><li>杭州湖滨</li><li>上海淮海路</li><li>北京三里屯</li></ol>",
    },
    {
        "id": "zhiji-after-sales",
        "name": "智己售后排障",
        "directory": "zhiji-after-sales",
        "fixture": "zhiji-after-sales-cases.json",
        "template": TemplateKey.SOP,
        "kind": WorkspaceResourceKind.FILE,
        "goal": "根据故障码、软件信号和历史案例生成售后排障 SOP。",
        "html": "<h1>智己售后排障</h1><h2>排查步骤</h2><ol><li>读取故障码和软件版本</li><li>核对信号与历史案例</li><li>执行复现、修复和复测</li></ol><p>升级条件：重复失败或出现安全告警。</p>",
    },
    {
        "id": "haidilao-inspection",
        "name": "海底捞门店巡检",
        "directory": "haidilao-inspection",
        "fixture": "haidilao-inspections.csv",
        "template": TemplateKey.DASHBOARD,
        "kind": WorkspaceResourceKind.FILE,
        "goal": "汇总门店巡检评分、异常项、负责人、期限和整改状态，并输出整改 SOP。",
        "html": "<h1>海底捞门店巡检</h1><p>平均评分 4.25 · 异常项 2 · 整改中 2</p><h2>整改 SOP</h2><ol><li>负责人确认异常</li><li>在期限前完成整改</li><li>复检并关闭事项</li></ol>",
    },
)
_SEED_LOCK = threading.RLock()


def _id(prefix: str, value: str) -> str:
    return f"{prefix}_demo_{hashlib.sha256(value.encode()).hexdigest()[:24]}"


def _zip_for(item: dict[str, Any]) -> bytes:
    package = ROOT / "demo" / "skills" / str(item["directory"])
    entries = {
        "SKILL.md": (package / "SKILL.md").read_bytes(),
        "manifest.json": (package / "manifest.json").read_bytes(),
        "output/index.html": (
            f"<!doctype html><html><head><meta charset='utf-8'><title>{item['name']}</title>"
            "<style>body{font:16px system-ui;margin:32px;color:#18212f}h1{color:#1769aa}</style>"
            f"</head><body>{item['html']}</body></html>"
        ).encode(),
        f"data/{item['fixture']}": (
            ROOT / "demo" / "fixtures" / str(item["fixture"])
        ).read_bytes(),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(entries.items()):
            archive.writestr(f"skillhub/{item['directory']}/{name}", content)
    return output.getvalue()


def _event(repository: Any, invocation_id: str, event_type: str, data: dict[str, Any]) -> None:
    cursor = len(repository.raw_events(invocation_id)) + 1
    repository.append_event(
        invocation_id,
        {"type": event_type, "data": data},
        {
            "id": f"{invocation_id}:{cursor}",
            "type": event_type,
            "invocation_id": invocation_id,
            "occurred_at": "2026-08-31T00:00:00+00:00",
            "data": data,
        },
        None,
    )


def ensure_demo_seed(actor: Actor, service: KnowledgeWorkspaceService) -> dict[str, Any]:
    """Create all three scenarios once for this tenant/workspace/principal."""
    with _SEED_LOCK:
        return _ensure_demo_seed_locked(actor, service)


def _ensure_demo_seed_locked(
    actor: Actor, service: KnowledgeWorkspaceService
) -> dict[str, Any]:
    existing = {
        draft.display_name: draft
        for draft in service.repository.list_drafts(
            tenant_id=actor.tenant_id, workspace_id=actor.workspace_id
        )
        if draft.display_name
        and draft.template_config.get("demo_seed_version") == SEED_VERSION
    }
    result: list[dict[str, str]] = []
    for item in SCENARIOS:
        if item["name"] in existing:
            draft = existing[item["name"]]
            session = service.repository.get_session(
                draft.draft_id,
                tenant_id=actor.tenant_id,
                workspace_id=actor.workspace_id,
            )
            revisions = service.repository.revisions(
                draft.draft_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id
            )
            artifacts = (
                service.repository.artifacts_for_revision(
                    revisions[0].revision_id,
                    tenant_id=actor.tenant_id,
                    workspace_id=actor.workspace_id,
                )
                if revisions
                else ()
            )
            pubs = service.repository.list_publications(
                tenant_id=actor.tenant_id, workspace_id=actor.workspace_id
            )
            pub = next((p for p in pubs if revisions and p.revision_id == revisions[0].revision_id), None)
            result.append({
                "scenario_id": item["id"], "resource_id": draft.resource_ids[0],
                "draft_id": draft.draft_id,
                "session_id": session.authoring_session_id if session else "",
                "revision_id": revisions[0].revision_id if revisions else "",
                "artifact_id": artifacts[0].artifact_id if artifacts else "",
                "publication_id": pub.publication_id if pub else "",
            })
            continue

        fixture = (ROOT / "demo" / "fixtures" / str(item["fixture"])).read_bytes()
        digest = hashlib.sha256(fixture).hexdigest()
        upload_id = _id("upload", f"{actor.tenant_id}:{actor.workspace_id}:{SEED_VERSION}:{item['id']}")
        upload_uri = service.repository.put_object(digest, fixture, suffix=".fixture")
        upload = WorkspaceUpload(
            tenant_id=actor.tenant_id, workspace_id=actor.workspace_id,
            upload_id=upload_id, filename=item["fixture"], sha256=digest,
            size_bytes=len(fixture), media_type="application/json" if str(item["fixture"]).endswith("json") else "text/csv",
            purpose="skill_input", uri=upload_uri,
        )
        service.repository.save_upload(upload)
        resource = WorkspaceResource(
            tenant_id=actor.tenant_id, workspace_id=actor.workspace_id,
            resource_id=_id("resource", upload_id), kind=item["kind"],
            display_name=f"{item['name']}示例数据", scope="personal", status="verified",
            source_id=upload_id,
            metadata={"filename": item["fixture"], "sha256": digest, "seed_version": SEED_VERSION},
        )
        service.repository.save_resource(resource)
        draft = service.create_draft(
            actor, item["goal"], (), display_name=item["name"],
            resource_ids=(resource.resource_id,), upload_ids=(upload_id,),
            template_key=item["template"],
            template_config={"demo_seed_version": SEED_VERSION, "provenance": "versioned_demo_bundle"},
            idempotency_key=_id("draft-key", item["id"]), request_digest=item["id"],
        )
        session = service.repository.get_session(
            draft.draft_id, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id
        )
        assert session is not None
        generate_id = _id("inv", f"{draft.draft_id}:generate")
        generate = Invocation(
            tenant_id=actor.tenant_id, workspace_id=actor.workspace_id,
            invocation_id=generate_id, draft_id=draft.draft_id,
            connection_ids=(), resource_ids=(resource.resource_id,), upload_ids=(upload_id,),
            authoring_session_id=session.authoring_session_id, kind=InvocationKind.GENERATE,
            status=InvocationStatus.SUCCEEDED, autoskill_agent_id=session.autoskill_agent_id,
            autoskill_session_id=session.autoskill_session_id, autoskill_request_id=_id("request", generate_id),
            autoskill_request_ids=(_id("request", generate_id),), principal_id=actor.principal_id,
            message=item["goal"], request_summary={
                "target_skill": item["directory"], "skill_version": "demo-1",
                "status": "succeeded",
                "policy_evaluation": {"satisfied": True, "matched_calls": [{
                    "action_id": "workspace.resource.read", "resource_ref": resource.resource_id
                }]},
            },
            request_summary_observed=True, final_answer_observed=True, done_observed=True,
            invocation_policy={"required_action_ids": [], "allowed_action_ids": ["workspace.resource.read"],
                               "resource_refs": [resource.resource_id]},
        )
        service.repository.save_invocation(generate)
        _event(service.repository, generate_id, "authoring.imported", {"provenance": "versioned_demo_bundle"})
        zip_bytes = _zip_for(item)
        zip_manifest = validate_skill_zip(zip_bytes)
        zip_uri = service.repository.put_object(zip_manifest["sha256"], zip_bytes, suffix=".zip")
        revision = SkillRevision(
            tenant_id=actor.tenant_id, workspace_id=actor.workspace_id,
            revision_id=_id("revision", draft.draft_id), draft_id=draft.draft_id, number=1,
            skill_name=item["directory"], template_key=item["template"],
            template_config=dict(draft.template_config), zip_uri=zip_uri,
            sha256=zip_manifest["sha256"],
            manifest={**zip_manifest, "provenance": "versioned_demo_bundle",
                      "resource_refs": [resource.resource_id], "connection_refs": []},
            created_from_invocation=generate_id,
        )
        service.repository.freeze_revision(revision)
        _event(service.repository, generate_id, "revision.created", {"revision_id": revision.revision_id})
        html = validate_html_artifact(
            f"<!doctype html><html><body>{item['html']}</body></html>".encode()
        )
        html_bytes = f"<!doctype html><html><body>{item['html']}</body></html>".encode()
        run_id = _id("inv", f"{draft.draft_id}:run")
        run = generate.model_copy(update={
            "invocation_id": run_id, "revision_id": revision.revision_id,
            "kind": InvocationKind.RUN, "lease_id": f"demo-lease-{item['id']}",
            "autoskill_request_id": _id("request", run_id),
            "autoskill_request_ids": (_id("request", run_id),),
            "request_summary": {
                "target_skill": item["directory"], "skill_version": "demo-1",
                "status": "succeeded",
                "policy_evaluation": {"satisfied": True, "matched_calls": [{
                    "action_id": "workspace.resource.read", "resource_ref": resource.resource_id
                }]},
            },
            "invocation_policy": {"required_action_ids": ["workspace.resource.read"],
                                  "allowed_action_ids": ["workspace.resource.read"],
                                  "resource_refs": [resource.resource_id]},
        })
        service.repository.save_invocation(run)
        _event(service.repository, run_id, "tool.call", {"action_id": "workspace.resource.read", "status": "succeeded"})
        artifact_digest = hashlib.sha256(html_bytes).hexdigest()
        artifact_uri = service.repository.put_object(artifact_digest, html_bytes, suffix=".html")
        artifact = Artifact(
            tenant_id=actor.tenant_id, workspace_id=actor.workspace_id,
            artifact_id=_id("artifact", revision.revision_id), revision_id=revision.revision_id,
            invocation_id=run_id, uri=artifact_uri, sha256=artifact_digest,
            media_type="text/html", encoding="utf-8", size_bytes=len(html_bytes),
            lineage={"source": "versioned_demo_bundle", "revision_id": revision.revision_id},
            csp=str(html["csp"]), sandbox=str(html["sandbox"]),
        )
        service.repository.save_artifact(artifact)
        _event(service.repository, run_id, "artifact.created", {"artifact_id": artifact.artifact_id})
        publication = service.publish(
            actor, revision.revision_id, "personal",
            idempotency_key=_id("publication-key", item["id"]), request_digest=revision.revision_id,
        )
        result.append({"scenario_id": item["id"], "resource_id": resource.resource_id,
                       "draft_id": draft.draft_id, "session_id": session.authoring_session_id,
                       "revision_id": revision.revision_id, "artifact_id": artifact.artifact_id,
                       "publication_id": publication.publication_id})
    return {"seed_version": SEED_VERSION, "scenarios": result}
