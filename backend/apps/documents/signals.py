import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.documents.models import DocumentVersion
from apps.documents.structure import build_structure

logger = logging.getLogger(__name__)


@receiver(post_save, sender=DocumentVersion)
def index_document(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        try:
            build_structure(instance.pk)
        except Exception:
            # Derived indexing must not discard the successfully saved original.
            logger.warning('文档结构索引失败，保留原文检索：version=%s', instance.pk)
