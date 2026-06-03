from .celery_tasks import ai_ping, fast_ping, heavy_ping
from apps.documents.tasks import generate_document_import_candidates

__all__ = ("ai_ping", "fast_ping", "heavy_ping", "generate_document_import_candidates")
