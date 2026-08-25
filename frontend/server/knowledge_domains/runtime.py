from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import FastAPI, File, Form, Header, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .service import DomainService, FeishuFetcher, fetch_feishu_document


class KnowledgeBaseInput(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    description: str = ""
    scope: str = "personal"


class FeishuInput(BaseModel):
    url: str = Field(min_length=1)
    includeChildren: bool = False


class QueryInput(BaseModel):
    question: str = Field(min_length=1)
    topK: int = Field(default=5, ge=1, le=20)


class SemanticInput(BaseModel):
    mdl: str
    sourceRevisionId: str | None = None


class SemanticRevisionInput(SemanticInput):
    expectedRevision: int = Field(ge=0)


class GraphMutationInput(BaseModel):
    operation: str
    entity: dict[str, object] | None = None
    relationship: dict[str, object] | None = None


class GraphQueryInput(BaseModel):
    mode: str = "neighbors"
    entityId: str | None = None
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None


def create_app(
    *,
    database_path: str | Path = ":memory:",
    identity_resolver: Callable[[Request], tuple[str, str]] | None = None,
    feishu_fetcher: FeishuFetcher | None = None,
) -> FastAPI:
    service = DomainService(database_path)
    app = FastAPI(title="Worker B Knowledge Domains", docs_url=None, redoc_url=None)
    mount_domain_routes(
        app,
        service=service,
        identity_resolver=identity_resolver
        or (lambda _request: ("workspace-worker-b", "editor")),
        feishu_fetcher=feishu_fetcher,
    )
    return app


def mount_domain_routes(
    app: FastAPI,
    *,
    service: DomainService,
    identity_resolver: Callable[[Request], tuple[str, str]],
    feishu_fetcher: FeishuFetcher | None = None,
) -> None:
    resolve_identity = identity_resolver

    def error(status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=status, content={"code": code, "message": message}
        )

    def can_mutate(role: str) -> bool:
        return role in {"editor", "admin"}

    @app.post("/api/knowledge-domains/v1/knowledge-bases")
    async def create_knowledge_base(body: KnowledgeBaseInput, request: Request):
        workspace, role = resolve_identity(request)
        if role not in {"editor", "admin"}:
            return error(403, "FORBIDDEN", "当前身份不能创建知识库。")
        return service.create_knowledge_base(
            workspace, body.name, body.description, body.scope
        )

    async def upload_to_kb(
        knowledge_base_id: str,
        file: UploadFile,
        title: str,
        description: str,
        tags: str,
        chunk_strategy: str,
        x_trace_id: str | None,
        workspace_id: str,
    ):
        try:
            service.knowledge_base_summary(knowledge_base_id, workspace_id)
            content = await file.read()
            return service.add_source(
                knowledge_base_id,
                filename=file.filename or "document",
                title=title,
                description=description,
                tags=tags,
                media_type=file.content_type or "application/octet-stream",
                content=content,
                chunk_strategy=chunk_strategy,
                trace_id=x_trace_id,
            )
        except KeyError:
            return error(404, "KNOWLEDGE_BASE_NOT_FOUND", "知识库不存在。")
        except (ValueError, UnicodeError) as exc:
            return error(422, "CONTENT_EXTRACTION_FAILED", str(exc))

    @app.post("/api/knowledge-domains/v1/knowledge-bases/{knowledge_base_id}/sources")
    async def upload_source(
        knowledge_base_id: str,
        request: Request,
        file: UploadFile = File(...),
        title: str = Form(""),
        description: str = Form(""),
        tags: str = Form(""),
        chunk_strategy: str = Form("auto"),
        x_trace_id: str | None = Header(default=None),
    ):
        workspace, role = resolve_identity(request)
        if not can_mutate(role):
            return error(403, "FORBIDDEN", "当前身份不能上传知识来源。")
        return await upload_to_kb(
            knowledge_base_id,
            file,
            title,
            description,
            tags,
            chunk_strategy,
            x_trace_id,
            workspace,
        )

    @app.post("/api/knowledge-domains/v1/documents")
    async def standalone_document(
        request: Request,
        file: UploadFile = File(...),
        title: str = Form(""),
        description: str = Form(""),
        tags: str = Form(""),
        chunk_strategy: str = Form("auto"),
        scope: str = Form("personal"),
    ):
        workspace, role = resolve_identity(request)
        if not can_mutate(role):
            return error(403, "FORBIDDEN", "当前身份不能创建文档。")
        content = await file.read()
        try:
            return service.standalone_document(
                workspace_id=workspace,
                filename=file.filename or "document",
                title=title,
                description=description,
                tags=tags,
                media_type=file.content_type or "application/octet-stream",
                content=content,
                chunk_strategy=chunk_strategy,
                scope=scope,
            )
        except (ValueError, UnicodeError) as exc:
            return error(422, "CONTENT_EXTRACTION_FAILED", str(exc))

    @app.get("/api/knowledge-domains/v1/documents/{source_id}")
    async def get_document(source_id: str, request: Request):
        workspace, _role = resolve_identity(request)
        try:
            return service.document(source_id, workspace)
        except KeyError:
            return error(404, "DOCUMENT_NOT_FOUND", "文档不存在。")

    @app.post("/api/knowledge-domains/v1/connectors/feishu/inspect")
    async def inspect_feishu(
        body: FeishuInput,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        resolve_identity(request)
        credential = (
            authorization.removeprefix("Bearer ").strip() if authorization else None
        )
        try:
            return service.inspect_feishu(
                body.url,
                credential,
                fetcher=feishu_fetcher or fetch_feishu_document,
            )
        except ValueError as exc:
            return error(422, "FEISHU_READ_FAILED", str(exc))

    @app.post(
        "/api/knowledge-domains/v1/knowledge-bases/{knowledge_base_id}/sources/feishu:sync"
    )
    async def sync_feishu(
        knowledge_base_id: str,
        body: FeishuInput,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        workspace, role = resolve_identity(request)
        if not can_mutate(role):
            return error(403, "FORBIDDEN", "当前身份不能同步知识来源。")
        credential = (
            authorization.removeprefix("Bearer ").strip() if authorization else None
        )
        try:
            service.knowledge_base_summary(knowledge_base_id, workspace)
            return service.sync_feishu(
                knowledge_base_id,
                body.url,
                credential,
                body.includeChildren,
                fetcher=feishu_fetcher or fetch_feishu_document,
            )
        except KeyError:
            return error(404, "KNOWLEDGE_BASE_NOT_FOUND", "知识库不存在。")
        except ValueError as exc:
            return error(422, "FEISHU_READ_FAILED", str(exc))

    @app.post("/api/knowledge-domains/v1/knowledge-bases/{knowledge_base_id}/query")
    async def ask(knowledge_base_id: str, body: QueryInput, request: Request):
        workspace, _role = resolve_identity(request)
        try:
            return service.ask(knowledge_base_id, body.question, body.topK, workspace)
        except KeyError:
            return error(404, "KNOWLEDGE_BASE_NOT_FOUND", "知识库不存在。")

    @app.get(
        "/api/knowledge-domains/v1/knowledge-bases/{knowledge_base_id}/query-results/{query_result_id}"
    )
    async def knowledge_query_result(
        knowledge_base_id: str, query_result_id: str, request: Request
    ):
        workspace, _role = resolve_identity(request)
        try:
            return service.knowledge_query_result(
                knowledge_base_id, query_result_id, workspace
            )
        except KeyError:
            return error(404, "KNOWLEDGE_QUERY_RESULT_NOT_FOUND", "问答结果不存在。")

    @app.get("/api/knowledge-domains/v1/knowledge-bases/{knowledge_base_id}")
    async def get_knowledge_base(knowledge_base_id: str, request: Request):
        workspace, _role = resolve_identity(request)
        try:
            return service.knowledge_base_summary(knowledge_base_id, workspace)
        except KeyError:
            return error(404, "KNOWLEDGE_BASE_NOT_FOUND", "知识库不存在。")

    @app.post("/api/knowledge-domains/v1/knowledge-bases/{knowledge_base_id}:publish")
    async def publish(knowledge_base_id: str, request: Request):
        workspace, role = resolve_identity(request)
        if not can_mutate(role):
            return error(403, "FORBIDDEN", "当前身份不能发布知识库。")
        try:
            return service.publish(knowledge_base_id, workspace)
        except KeyError:
            return error(404, "KNOWLEDGE_BASE_NOT_FOUND", "知识库不存在。")

    @app.get("/api/knowledge-domains/v1/semantic-models/{resource_id}")
    async def semantic_model(resource_id: str, request: Request):
        workspace, _role = resolve_identity(request)
        try:
            return service.get_semantic(resource_id, workspace)
        except PermissionError:
            return error(404, "SEMANTIC_MODEL_NOT_FOUND", "语义模型不存在。")

    @app.post("/api/knowledge-domains/v1/semantic-models/{resource_id}:validate")
    async def validate_semantic(
        resource_id: str, body: SemanticInput, request: Request
    ):
        resolve_identity(request)
        del resource_id
        return service.validate_semantic(body.mdl, body.sourceRevisionId)

    @app.get("/api/knowledge-domains/v1/semantic-source-revisions")
    async def semantic_source_revisions(request: Request):
        workspace, _role = resolve_identity(request)
        return {"items": service.source_revisions(workspace)}

    @app.post("/api/knowledge-domains/v1/semantic-models/{resource_id}/revisions")
    async def save_semantic(
        resource_id: str, body: SemanticRevisionInput, request: Request
    ):
        workspace, role = resolve_identity(request)
        if not can_mutate(role):
            return error(403, "FORBIDDEN", "当前身份不能保存语义模型。")
        try:
            return service.save_semantic(
                resource_id,
                body.mdl,
                body.expectedRevision,
                body.sourceRevisionId,
                workspace,
            )
        except RuntimeError as exc:
            return error(409, "SEMANTIC_REVISION_CONFLICT", str(exc))
        except ValueError as exc:
            return error(422, "SEMANTIC_VALIDATION_FAILED", str(exc))
        except PermissionError:
            return error(404, "SEMANTIC_MODEL_NOT_FOUND", "语义模型不存在。")

    @app.get("/api/knowledge-domains/v1/graphs/{resource_id}")
    async def graph(resource_id: str, request: Request):
        workspace, _role = resolve_identity(request)
        try:
            return service.graph(resource_id, workspace)
        except PermissionError:
            return error(404, "GRAPH_NOT_FOUND", "知识图谱不存在。")

    @app.post("/api/knowledge-domains/v1/graphs/{resource_id}/mutations")
    async def mutate_graph(
        resource_id: str, body: GraphMutationInput, request: Request
    ):
        workspace, role = resolve_identity(request)
        if not can_mutate(role):
            return error(403, "FORBIDDEN", "当前身份不能修改知识图谱。")
        try:
            return service.mutate_graph(
                resource_id, body.model_dump(exclude_none=True), workspace
            )
        except ValueError as exc:
            return error(422, "GRAPH_MUTATION_INVALID", str(exc))
        except PermissionError:
            return error(404, "GRAPH_NOT_FOUND", "知识图谱不存在。")

    @app.post("/api/knowledge-domains/v1/graphs/{resource_id}/queries")
    async def query_graph(resource_id: str, body: GraphQueryInput, request: Request):
        workspace, _role = resolve_identity(request)
        try:
            return service.query_graph(
                resource_id,
                {
                    "mode": body.mode,
                    "entityId": body.entityId,
                    "from": body.from_,
                    "to": body.to,
                },
                workspace,
            )
        except ValueError as exc:
            return error(422, "GRAPH_QUERY_INVALID", str(exc))
        except PermissionError:
            return error(404, "GRAPH_NOT_FOUND", "知识图谱不存在。")

    @app.get("/api/knowledge-domains/v1/graphs/{resource_id}/queries/{query_result_id}")
    async def graph_query_result(
        resource_id: str, query_result_id: str, request: Request
    ):
        workspace, _role = resolve_identity(request)
        try:
            return service.graph_query_result(resource_id, query_result_id, workspace)
        except KeyError:
            return error(404, "GRAPH_QUERY_RESULT_NOT_FOUND", "图查询结果不存在。")
        except PermissionError:
            return error(404, "GRAPH_QUERY_RESULT_NOT_FOUND", "图查询结果不存在。")
