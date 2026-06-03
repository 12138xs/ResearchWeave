from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.experiments.models import ExperimentProject


def experiment_queryset(params=None) -> QuerySet[ExperimentProject]:
    params = params or {}
    queryset = ExperimentProject.objects.select_related("paper", "document", "space", "owner").prefetch_related("runs")
    status = params.get("status")
    if status and status != "all":
        queryset = queryset.filter(status=status)
    space = params.get("space")
    if space and str(space).isdigit():
        queryset = queryset.filter(space_id=int(space))
    paper = params.get("paper")
    if paper and str(paper).isdigit():
        queryset = queryset.filter(paper_id=int(paper))
    query = str(params.get("q") or "").strip()
    if query:
        queryset = queryset.filter(
            Q(title__icontains=query)
            | Q(objective__icontains=query)
            | Q(protocol_markdown__icontains=query)
            | Q(repo_url__icontains=query)
        )
    return queryset


def experiment_index_projection():
    for experiment in experiment_queryset({}).all():
        keywords = []
        if experiment.space:
            keywords.append(experiment.space.name)
        yield {
            "object_type": "experiment",
            "object_id": experiment.id,
            "title": experiment.title,
            "summary": experiment.objective,
            "body": "\n".join([experiment.protocol_markdown, experiment.repo_url]),
            "space_id": experiment.space_id,
            "keywords_json": keywords,
            "source_updated_at": experiment.updated_at,
        }
