"""Knowledge Workspace V1 AutoSkill adapter and immutable asset boundary."""

from .autoskill import (
    AutoSkillClient,
    AutoSkillConfig,
    AutoSkillProtocolError,
    UnavailableAutoSkillClient,
)
from .connection import ConnectionInvocationContextPort, EphemeralConnectionContext
from .html_artifact import HtmlArtifactError, validate_output_archive
from .models import (
    Artifact,
    AuthoringSession,
    Invocation,
    InvocationKind,
    InvocationStatus,
    Publication,
    SkillDraft,
    SkillRevision,
    WorkspaceUpload,
)
from .repository import KnowledgeWorkspaceRepository
from .routes import mount_knowledge_workspace_routes
from .service import Actor, KnowledgeWorkspaceService
from .sse import SseParser, normalize_upstream_event
from .zip_validator import SkillZipError, validate_skill_zip

__all__ = [
    "Artifact",
    "Actor",
    "AuthoringSession",
    "AutoSkillClient",
    "AutoSkillConfig",
    "AutoSkillProtocolError",
    "ConnectionInvocationContextPort",
    "EphemeralConnectionContext",
    "UnavailableAutoSkillClient",
    "HtmlArtifactError",
    "Invocation",
    "InvocationKind",
    "InvocationStatus",
    "KnowledgeWorkspaceRepository",
    "KnowledgeWorkspaceService",
    "mount_knowledge_workspace_routes",
    "Publication",
    "SkillDraft",
    "SkillRevision",
    "WorkspaceUpload",
    "SkillZipError",
    "SseParser",
    "normalize_upstream_event",
    "validate_output_archive",
    "validate_skill_zip",
]
