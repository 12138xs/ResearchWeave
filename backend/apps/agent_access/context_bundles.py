from __future__ import annotations

import hashlib
import json

from django.db import transaction
from django.db.models import OuterRef, Subquery
from rest_framework.exceptions import APIException

from apps.agent_access.contracts import material_evidence_reference
from apps.agent_access.models import ResearchContextBundle
from apps.materials.models import Evidence, MaterialVersion
from apps.materials.selectors import externally_accessible_materials
from apps.search.evidence import query_terms, search_evidence


CLIENT_COPY_WARNING = (
    "A510 can block future reads after permission changes, but cannot recall content already sent to a client."
)
KEYWORD_RETRIEVER_VERSION = "keyword-v1"


class BundleSourceUnavailable(APIException):
    status_code = 409
    default_code = "bundle_source_unavailable"

    def __init__(self, *, unavailable_count: int):
        super().__init__({
            "code": self.default_code,
            "detail": "One or more frozen sources are no longer available under current permissions.",
            "unavailable_count": unavailable_count,
        })


class BundleIntegrityError(APIException):
    status_code = 409
    default_code = "bundle_integrity_error"
    default_detail = {"code": default_code, "detail": "The frozen context bundle failed its integrity check."}


def canonical_digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def digest_payload(*, question, scope, retrieval_manifest, evidence_manifest, missing_information):
    return {
        "question": question,
        "scope": scope,
        "retrieval_manifest": retrieval_manifest,
        "evidence": evidence_manifest,
        "missing_information": missing_information,
    }


def evidence_entry(result: dict[str, object]) -> dict[str, object]:
    row = result["_evidence"]
    version = row.version
    return {
        "source": material_evidence_reference(row),
        "location": {
            "page": row.page,
            "line_start": row.line_start,
            "line_end": row.line_end,
        },
        "excerpt": result["excerpt"],
        "review_status": "needs_review" if row.review_required else "reviewed",
        "score": {"keyword": result["score"]},
        "version_sha256": version.sha256,
    }


@transaction.atomic
def build_context_bundle(*, user, token, question: str, material_ids: list[int], limit: int):
    requested_ids = sorted(set(material_ids))
    allowed = externally_accessible_materials(user)
    if requested_ids:
        allowed = allowed.filter(pk__in=requested_ids)
        allowed_count = allowed.count()
        if allowed_count != len(requested_ids):
            raise BundleSourceUnavailable(unavailable_count=len(requested_ids) - allowed_count)
    results = search_evidence(
        user,
        {"q": question, "limit": limit, "mode": "keyword"},
        allowed_materials=allowed,
        include_evidence_objects=True,
    )
    selected_material_ids = sorted({row["material_id"] for row in results["results"]})
    if selected_material_ids:
        locked_ids = set(
            externally_accessible_materials(user)
            .select_for_update()
            .filter(pk__in=selected_material_ids)
            .values_list("pk", flat=True)
        )
        if locked_ids != set(selected_material_ids):
            raise BundleSourceUnavailable(unavailable_count=len(set(selected_material_ids) - locked_ids))
    evidence_manifest = [evidence_entry(row) for row in results["results"]]
    scope = {
        "material_ids": requested_ids,
        "visibility": sorted(set(allowed.values_list("visibility", flat=True))),
    }
    selection = [
        {
            **entry["source"]["identity"],
            "version_sha256": entry["version_sha256"],
        }
        for entry in evidence_manifest
    ]
    retrieval_manifest = {
        "mode": "keyword",
        "retriever_version": KEYWORD_RETRIEVER_VERSION,
        "query_terms": query_terms(question),
        "filters": {"material_ids": requested_ids},
        "limits": {"evidence": limit},
        "selected_sources": selection,
        "candidate_limit_reached": results["candidate_limit_reached"],
        "degraded": False,
    }
    missing = [] if evidence_manifest else ["No matching evidence was found in the approved external scope."]
    payload = digest_payload(
        question=question,
        scope=scope,
        retrieval_manifest=retrieval_manifest,
        evidence_manifest=evidence_manifest,
        missing_information=missing,
    )
    bundle = ResearchContextBundle.objects.create(
        owner=user,
        created_by_token=token,
        question=question,
        scope_json=scope,
        retrieval_manifest=retrieval_manifest,
        evidence_manifest=evidence_manifest,
        missing_information=missing,
        warnings=[CLIENT_COPY_WARNING],
        content_digest=canonical_digest(payload),
    )
    return bundle_response(bundle)


def validate_bundle_integrity(bundle):
    actual = canonical_digest(digest_payload(
        question=bundle.question,
        scope=bundle.scope_json,
        retrieval_manifest=bundle.retrieval_manifest,
        evidence_manifest=bundle.evidence_manifest,
        missing_information=bundle.missing_information,
    ))
    if actual != bundle.content_digest:
        raise BundleIntegrityError()


def live_bundle_warnings(bundle, user):
    identities = [entry["source"]["identity"] for entry in bundle.evidence_manifest]
    evidence_ids = [identity["evidence_id"] for identity in identities]
    rows = {
        row.pk: row
        for row in Evidence.objects.filter(pk__in=evidence_ids).select_related("version__material")
    }
    allowed_material_ids = set(externally_accessible_materials(user).values_list("pk", flat=True))
    scoped_material_ids = set(bundle.scope_json.get("material_ids") or [])
    unavailable_sources = {
        ("material", material_id) for material_id in scoped_material_ids - allowed_material_ids
    }
    warnings = list(bundle.warnings)
    latest = MaterialVersion.objects.filter(
        material_id=OuterRef("version__material_id"),
        status__in=["ready", "needs_review"],
    ).order_by("-number").values("pk")[:1]
    live_rows = Evidence.objects.filter(pk__in=evidence_ids).annotate(latest_version_id=Subquery(latest))
    latest_by_evidence = {row.pk: row.latest_version_id for row in live_rows}
    for entry, identity in zip(bundle.evidence_manifest, identities):
        row = rows.get(identity["evidence_id"])
        if (
            row is None
            or row.version_id != identity["version_id"]
            or row.version.material_id != identity["material_id"]
            or row.version.material_id not in allowed_material_ids
            or row.version.status not in {"ready", "needs_review"}
        ):
            unavailable_sources.add(("evidence", identity["evidence_id"]))
            continue
        if latest_by_evidence.get(row.pk) != row.version_id:
            warnings.append({
                "code": "source_version_not_latest",
                "source": entry["source"],
                "detail": "The bundle keeps its frozen version; a newer version exists and was not substituted.",
            })
        if row.version.material.source_kind != entry["source"]["source_kind"]:
            warnings.append({
                "code": "source_metadata_changed",
                "source": entry["source"],
                "detail": "The stored source kind differs from current metadata; the frozen value was not replaced.",
            })
    if unavailable_sources:
        raise BundleSourceUnavailable(unavailable_count=len(unavailable_sources))
    return warnings


def bundle_response(bundle, *, warnings=None):
    return {
        "bundle_id": bundle.bundle_id,
        "schema_version": bundle.schema_version,
        "created_at": bundle.created_at,
        "created_for_user": bundle.owner_id,
        "question": bundle.question,
        "scope": bundle.scope_json,
        "retrieval_manifest": bundle.retrieval_manifest,
        "evidence": bundle.evidence_manifest,
        "missing_information": bundle.missing_information,
        "warnings": bundle.warnings if warnings is None else warnings,
        "content_digest": bundle.content_digest,
    }


def retrieve_context_bundle(bundle, *, user):
    validate_bundle_integrity(bundle)
    warnings = live_bundle_warnings(bundle, user)
    return bundle_response(bundle, warnings=warnings)
