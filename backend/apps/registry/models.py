"""旁路身份登记；旧业务实体及其授权仍为权威。"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


OBJECT_TYPES = ('material', 'paper', 'document', 'experiment_project', 'experiment_run')
BINDING_FIELDS = tuple(f'{kind}_id' for kind in OBJECT_TYPES)


def exactly_one(fields):
    result = Q(pk__isnull=True) & Q(pk__isnull=False)
    for chosen in fields:
        clause = Q()
        for field in fields:
            clause &= Q(**{f'{field}__isnull': field != chosen})
        result |= clause
    return result


class ResearchObject(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    object_type = models.CharField(max_length=24, choices=[(x, x) for x in OBJECT_TYPES])
    title = models.CharField(max_length=500)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    ownership_state = models.CharField(max_length=20)
    policy_origin = models.CharField(max_length=20, default='legacy_adapter')
    observation_sha256 = models.CharField(max_length=64)
    current_revision = models.ForeignKey('ResearchRevision', null=True, on_delete=models.SET_NULL, related_name='+')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    observed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(object_type__in=OBJECT_TYPES), name='registry_object_type'),
            models.CheckConstraint(condition=Q(ownership_state__in=('known', 'unresolved', 'team_custody')), name='registry_ownership_state'),
            models.CheckConstraint(condition=Q(policy_origin='legacy_adapter'), name='registry_legacy_policy'),
        ]


class ResearchObjectBinding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    research_object = models.OneToOneField(ResearchObject, on_delete=models.CASCADE, related_name='binding')
    material = models.ForeignKey('materials.Material', null=True, on_delete=models.CASCADE, related_name='+')
    paper = models.ForeignKey('papers.Paper', null=True, on_delete=models.CASCADE, related_name='+')
    document = models.ForeignKey('documents.Document', null=True, on_delete=models.CASCADE, related_name='+')
    experiment_project = models.ForeignKey('experiments.ExperimentProject', null=True, on_delete=models.CASCADE, related_name='+')
    experiment_run = models.ForeignKey('experiments.ExperimentRun', null=True, on_delete=models.CASCADE, related_name='+')

    class Meta:
        constraints = [models.CheckConstraint(condition=exactly_one(BINDING_FIELDS), name='registry_binding_exactly_one')] + [
            models.UniqueConstraint(fields=[kind], condition=Q(**{f'{kind}__isnull': False}), name=f'registry_bind_{kind}')
            for kind in OBJECT_TYPES
        ]


class ResearchRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    research_object = models.ForeignKey(ResearchObject, on_delete=models.CASCADE, related_name='revisions')
    number = models.PositiveIntegerField()
    operation_key = models.CharField(max_length=120)
    payload_kind = models.CharField(max_length=24)
    material_version = models.ForeignKey('materials.MaterialVersion', null=True, on_delete=models.CASCADE, related_name='+')
    document_version = models.ForeignKey('documents.DocumentVersion', null=True, on_delete=models.CASCADE, related_name='+')
    snapshot = models.JSONField(null=True)
    schema_version = models.CharField(max_length=32, default='registry-v1')
    canonicalization_version = models.CharField(max_length=32, default='json-sorted-utf8-v1')
    # File hash is an existing declaration, NOT a re-verification of blob bytes.
    file_sha256 = models.CharField(max_length=64, null=True)
    content_sha256 = models.CharField(max_length=64, null=True)
    metadata_sha256 = models.CharField(max_length=64)
    observation_sha256 = models.CharField(max_length=64)
    source_kind = models.CharField(max_length=40)
    generator_kind = models.CharField(max_length=16, default='system')
    generator_name = models.CharField(max_length=32, default='registry_adapter')
    generator_version = models.CharField(max_length=16, default='1')
    source_revision = models.ForeignKey('self', null=True, on_delete=models.SET_NULL, related_name='+')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    observed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(number__gt=0), name='registry_revision_positive'),
            models.UniqueConstraint(fields=['research_object', 'number'], name='registry_revision_number'),
            models.UniqueConstraint(fields=['research_object', 'operation_key'], name='registry_operation_once'),
            models.CheckConstraint(condition=(
                Q(payload_kind='material_version', material_version__isnull=False, document_version__isnull=True, snapshot__isnull=True)
                | Q(payload_kind='document_version', material_version__isnull=True, document_version__isnull=False, snapshot__isnull=True)
                | Q(payload_kind='baseline_snapshot', material_version__isnull=True, document_version__isnull=True, snapshot__isnull=False)
            ), name='registry_revision_payload'),
            models.UniqueConstraint(fields=['material_version'], condition=Q(material_version__isnull=False), name='registry_material_version_once'),
            models.UniqueConstraint(fields=['document_version'], condition=Q(document_version__isnull=False), name='registry_document_version_once'),
        ]
