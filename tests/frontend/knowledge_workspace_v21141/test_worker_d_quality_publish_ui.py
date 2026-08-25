from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OWNED_FILES = [
    ROOT / "frontend/src/knowledge-workspace/frozen-ui/components/MainArea/EvaluationCenterView.tsx",
    ROOT / "frontend/src/knowledge-workspace/frozen-ui/components/RightPane/EvaluationDrawer.tsx",
    ROOT / "frontend/src/knowledge-workspace/frozen-ui/components/RightPane/CommentThread.tsx",
    ROOT / "frontend/src/knowledge-workspace/frozen-ui/components/Modals/PublishAgentModal.tsx",
    ROOT / "frontend/src/knowledge-workspace/frozen-ui/components/Modals/AgentResourceSelectorModal.tsx",
    ROOT / "frontend/src/knowledge-workspace/frozen-ui/components/Modals/ShareModal.tsx",
    ROOT / "frontend/src/knowledge-workspace/frozen-ui/components/Modals/VersionHistoryModal.tsx",
    ROOT / "frontend/src/knowledge-workspace/frozen-ui/components/Modals/ExportModal.tsx",
    ROOT / "frontend/src/knowledge-workspace/frozen-ui/components/Modals/AlertModal.tsx",
    ROOT / "frontend/src/knowledge-workspace/frozen-ui/components/Modals/ActionPolicyModal.tsx",
    ROOT / "frontend/src/knowledge-workspace/frozen-ui/lib/qualityPublicationClient.ts",
]


def test_worker_d_owned_ui_has_no_browser_persistence_or_fake_async_success() -> None:
    findings: list[str] = []
    forbidden = {
        "localStorage": re.compile(r"\blocalStorage\b"),
        "timer-fake-success": re.compile(r"\bset(?:Timeout|Interval)\s*\("),
        "success-toast": re.compile(
            r"showToast(?:\?\.)?\([^;\n]*(?:成功|已成功|创建|发布|同步|上传|执行|应用|验证|完成|提交|绑定|授权|生效|撤销|回滚|修复|导出|生成)"
        ),
    }
    for path in OWNED_FILES:
        source = path.read_text(encoding="utf-8")
        for label, pattern in forbidden.items():
            if pattern.search(source):
                findings.append(f"{path.relative_to(ROOT)}:{label}")
    assert findings == []


def test_worker_d_ui_uses_real_commands_and_documents_shared_contract_gaps() -> None:
    sources = "\n".join(path.read_text(encoding="utf-8") for path in OWNED_FILES)
    for command in [
        "evaluation-suite.create",
        "evaluation-case.import",
        "evaluation-case.adopt-history",
        "evaluation-case.generate-candidates",
        "evaluation-case.confirm-candidates",
        "evaluation-run.start",
        "evaluation-run.cancel",
        "evaluation-run.resume",
        "evaluation-run.retry",
        "evaluation-fix.propose",
        "evaluation-fix.propose-all-unresolved",
        "evaluation-fix.apply",
        "evaluation-fix.undo",
        "policy-gate.evaluate",
        "resource.share",
        "artifact.export",
        "refresh.run",
        "invocation.start",
        "action.update",
    ]:
        assert command in sources
    assert "inline://agent-selector-input" not in sources
    assert "browser-not-authoritative" not in sources

    proposal = (
        ROOT
        / "docs/knowledge-assets/implementation/STEP3_WORKER_D_CONTRACT_PROPOSAL.md"
    ).read_text(encoding="utf-8")
    for required in [
        "PublicationPublishPayload.visibility",
        "RefreshSchedule",
        "AlertRule",
        "CommentThread",
        "server-derived callerId",
    ]:
        assert required in proposal


def test_worker_d_evaluation_preserves_confirmed_cases_and_persisted_suite_version() -> None:
    evaluation_center = (
        ROOT
        / "frontend/src/knowledge-workspace/frozen-ui/components/MainArea/EvaluationCenterView.tsx"
    ).read_text(encoding="utf-8")
    helper = (
        ROOT
        / "frontend/src/knowledge-workspace/frozen-ui/lib/qualityPublicationClient.ts"
    ).read_text(encoding="utf-8")

    assert "candidateConfirmed = false" in helper
    assert "candidateConfirmed," in helper
    assert "Boolean(item.confirmed)" in evaluation_center
    assert "const persistedVersion = await createSuite();" in evaluation_center
    assert "suiteVersion: persistedVersion" in evaluation_center


def test_worker_d_fail_closes_missing_main_contracts_instead_of_faking_persistence() -> None:
    publish_modal = (
        ROOT
        / "frontend/src/knowledge-workspace/frozen-ui/components/Modals/PublishAgentModal.tsx"
    ).read_text(encoding="utf-8")
    action_policy_modal = (
        ROOT
        / "frontend/src/knowledge-workspace/frozen-ui/components/Modals/ActionPolicyModal.tsx"
    ).read_text(encoding="utf-8")
    comment_thread = (
        ROOT
        / "frontend/src/knowledge-workspace/frozen-ui/components/RightPane/CommentThread.tsx"
    ).read_text(encoding="utf-8")

    assert "PublicationPublishPayload.visibility" in publish_modal
    assert "publication.publish 当前 fail closed" in publish_modal
    assert "command: 'publication.publish'" not in publish_modal
    assert 'command: "publication.publish"' not in publish_modal
    assert "visibilityAcknowledged" not in publish_modal

    assert "action.update 只记录审计意图" in action_policy_modal
    assert "showToast" not in action_policy_modal

    assert "不能在浏览器伪造评论记录" in comment_thread
    assert "setComments" not in comment_thread
    assert "setComments((current)" not in comment_thread
