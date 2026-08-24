"""Agent orchestration and SkillDraft authoring domain.

This package intentionally exposes ports and read models only.  The shared
Studio application composition and BFF route registration remain owned by
STEP 3 Main.
"""

from .models import (
    AuthoringOperation,
    BuildPlan,
    ContextEnvelope,
    DraftRevision,
    PatchProposal,
    SkillAuthoringError,
)
from .ports import (
    AgentKitModelGateway,
    CredentialBlockedGateway,
    InMemoryResourceResolver,
    JsonFileAuthoringRepository,
    LocalPlanningHarness,
    NoopWorker3Executor,
)
from .service import SkillAuthoringService

__all__ = [
    "AgentKitModelGateway",
    "AuthoringOperation",
    "BuildPlan",
    "ContextEnvelope",
    "CredentialBlockedGateway",
    "DraftRevision",
    "InMemoryResourceResolver",
    "JsonFileAuthoringRepository",
    "LocalPlanningHarness",
    "NoopWorker3Executor",
    "PatchProposal",
    "SkillAuthoringError",
    "SkillAuthoringService",
]
