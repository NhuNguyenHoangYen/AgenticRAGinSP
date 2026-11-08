"""Milestone D API. Run: python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000."""
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pymongo.errors import PyMongoError
from starlette.exceptions import HTTPException

from src.api.config import APISettings
from src.api.errors import APIError, error_response
from src.api.routes.chats import router
from src.api.routes.workflows import router as workflows_router
from src.api.schemas.foundation import ErrorResponse, HealthResponse
from src.observability import RequestContext, configure_logging, get_logger, request_context
from src.repositories.mongo import MongoDatabase
from src.repositories.records import Repositories
from src.services.errors import ServiceError

log = get_logger(__name__)


def create_app(settings=None):
    try:
        settings = settings or APISettings.from_env()
    except Exception:
        log.exception("api.configuration_failed")
        raise

    @asynccontextmanager
    async def lifespan(app):
        configure_logging()
        mongo = None
        started = perf_counter()
        startup_completed = False
        stage = "mongodb_client"
        log.info("api.startup_started", identity_mode="development", milestone="D",
                 database_name=settings.mongodb_database)
        try:
            try:
                mongo = MongoDatabase(settings)
                stage = "mongodb_initialize"
                await mongo.initialize()
                repositories = Repositories(mongo.database)
                stage = "development_identity"
                await repositories.users.ensure_development_user(settings)
                app.state.mongo = mongo
                app.state.repositories = repositories
                from src.storage.local_files import LocalFileStorage
                from src.services.rag_pipeline import RAGPipeline
                app.state.storage = LocalFileStorage(settings.upload_directory)
                app.state.pipeline = RAGPipeline(settings)
                startup_completed = True
                log.info("api.started", identity_mode="development", milestone="D",
                         duration_ms=round((perf_counter() - started) * 1000, 2))
            except Exception:
                log.exception("api.startup_failed", stage=stage)
                raise
            yield
        finally:
            shutdown_started = perf_counter()
            log.info("api.shutdown_started", startup_completed=startup_completed)
            try:
                if mongo is not None:
                    await mongo.close()
            except Exception:
                log.exception("api.shutdown_failed")
                raise
            log.info("api.stopped", duration_ms=round((perf_counter() - shutdown_started) * 1000, 2))

    app = FastAPI(
        title="AgenticRAG API", version="0.5.0", lifespan=lifespan,
        description="Milestone E: Streamlit API client with scoped multi-document QA and citations. Separate ingestion worker required.",
    )
    app.state.settings = settings

    @app.middleware("http")
    async def correlate_request(request: Request, call_next):
        request.state.request_id = uuid4().hex
        path = request.url.path
        pieces = path.split("/")
        chat_id = pieces[4] if path.startswith("/api/v1/chats/") and len(pieces) > 4 else None
        context = RequestContext(user_id=settings.development_user_id, chat_id=chat_id,
                                 request_id=request.state.request_id)
        client_request_id = request.headers.get('X-Client-Request-ID', '')
        if len(client_request_id) != 32 or any(c not in '0123456789abcdef' for c in client_request_id):
            client_request_id = None
        started = perf_counter()
        with request_context(context):
            log.info("api.request_started", method=request.method, path=path, client_request_id=client_request_id)
            try:
                declared_size = request.headers.get("content-length")
                upload = request.method == "POST" and path.endswith("/documents")
                if upload and declared_size and (not declared_size.isdigit() or int(declared_size) > settings.upload_batch_bytes+1024*1024):
                    log.warning("upload.request_rejected", error_code="upload_too_large")
                    response = error_response(request, 413, "upload_too_large", "Upload request exceeds the size limit")
                else:
                    response = await call_next(request)
            except Exception:
                log.exception("api.request_failed")
                response = error_response(request, 500, "internal_error", "An unexpected server error occurred")
            response.headers["X-Request-ID"] = request.state.request_id
            log.info("api.request_completed", status_code=response.status_code, client_request_id=client_request_id,
                     duration_ms=round((perf_counter() - started) * 1000, 2))
            return response

    @app.exception_handler(APIError)
    async def handle_application_error(request, error):
        emit = log.error if error.status_code >= 500 else log.warning
        emit("api.application_rejected", error_code=error.code, status_code=error.status_code)
        return error_response(request, error.status_code, error.code, error.message)

    @app.exception_handler(ServiceError)
    async def handle_service_error(request, error):
        status_code = {
            "chat_not_found": 404, "attachment_inconsistent": 409, "chat_not_active": 409,
            "single_document_limit": 409, "chat_changed": 409, "document_required": 409,
            "document_not_ready": 409, "embedding_profile_changed": 409,
            "invalid_document": 422, "ingestion_failed": 503, "generation_failed": 503,
            "message_persistence_failed": 503, "document_not_found": 404,
            "job_not_found": 404, "job_not_retryable": 409, "attachment_limit": 409,
            "original_unavailable": 404,"document_not_accessible":404,"no_ready_documents":409,
            "comparison_requires_documents":422,"comparison_budget_too_small":422,
            "retrieval_scope_violation":503,"invalid_answer_format":502,"invalid_citations":502,
            "incomplete_comparison":502,"invalid_scope":422,
        }.get(error.code, 500)
        emit = log.error if status_code >= 500 else log.warning
        emit("api.service_rejected", error_code=error.code, status_code=status_code)
        return error_response(request, status_code, error.code, str(error), getattr(error, "details", None))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request, error):
        # Omit raw input and exception context, which can contain private values.
        details = [{"location": list(item["loc"]), "type": item["type"], "message": item["msg"]}
                   for item in error.errors()]
        log.warning("api.validation_rejected", error_code="invalid_request", status_code=422,
                    invalid_fields=[item["location"] for item in details])
        return error_response(request, 422, "invalid_request", "Request validation failed", details)

    @app.exception_handler(HTTPException)
    async def handle_http_error(request, error):
        emit = log.error if error.status_code >= 500 else log.warning
        emit("api.http_rejected", status_code=error.status_code)
        return error_response(request, error.status_code, "http_error", str(error.detail))

    @app.exception_handler(PyMongoError)
    async def handle_database_error(request, error):
        log.exception("database.operation_failed")
        return error_response(request, 503, "database_unavailable", "Database operation unavailable; retry later")

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    async def health():
        return HealthResponse(status="ok")

    @app.get("/health/ready", response_model=HealthResponse,
             responses={503: {"model": ErrorResponse}}, tags=["health"])
    async def readiness(request: Request):
        await request.app.state.mongo.ping()
        return HealthResponse(status="ready")

    app.include_router(router, prefix="/api/v1", responses={
        code: {"model": ErrorResponse} for code in (401, 404, 409, 422, 500, 503)
    })
    app.include_router(workflows_router, prefix="/api/v1", responses={
        code: {"model": ErrorResponse} for code in (401, 404, 409, 413, 422, 500, 502, 503)
    })
    return app


app = create_app()
