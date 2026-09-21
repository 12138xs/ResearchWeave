"""F01–F18：合成数据上的旧质量入口权限与存在性合同。"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.documents.models import Document
from apps.experiments.models import ExperimentProject
from apps.materials.models import Material, MaterialVersion
from apps.papers.models import Paper
from apps.quality.models import QualityIssue
from apps.quality.selectors import quality_issue_queryset
from apps.quality.serializers import QualityIssueSerializer
from apps.quality.services import run_quality_audit
from apps.quality.views import QualityIssueDetailView, QualityIssueListView
from apps.tasks.models import TaskRecord


class QualityAccessBoundaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.owner = users.create_user(username="quality_owner")
        cls.other = users.create_user(username="quality_other")
        cls.staff = users.create_user(username="quality_staff", is_staff=True)
        cls.paper = Paper.objects.create(title="Synthetic paper")
        cls.document = Document.objects.create(title="Synthetic document")
        cls.project = ExperimentProject.objects.create(title="Synthetic project", owner=cls.owner)

    def setUp(self):
        self.factory = APIRequestFactory()
        self.publisher = patch("apps.quality.tasks.run_quality_audit_task.delay").start()
        self.addCleanup(patch.stopall)

    def tearDown(self):
        self.publisher.assert_not_called()

    def issue(self, kind="experiment", target=None, **kwargs):
        return QualityIssue.objects.create(
            object_type=kind, object_id=self.project.pk if target is None else target,
            dimension=kwargs.pop("dimension", "metadata"), **kwargs,
        )

    def call(self, user, method="get", issue=None, data=None, query=None):
        path = "/api/quality/issues/" if issue is None else f"/api/quality/issues/{issue}/"
        if method == "get":
            request = self.factory.get(path, query or {})
        else:
            request = getattr(self.factory, method)(path, data or {}, format="json")
        if user is not None:
            force_authenticate(request, user=user)
        view = QualityIssueListView if issue is None else QualityIssueDetailView
        response = view.as_view()(request, **({} if issue is None else {"pk": issue}))
        response.render()
        return response

    def ids(self, user, query=None):
        response = self.call(user, query=query)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, list)
        return {row["id"] for row in response.data}

    def sources(self):
        return {model._meta.label: list(model.objects.order_by("pk").values())
                for model in (Paper, Document, ExperimentProject, Material, MaterialVersion, TaskRecord)}

    def denied(self, user, issue, payload=None):
        before = QualityIssue.objects.filter(pk=issue.pk).values().get()
        sources = self.sources()
        for method in ("patch", "put"):
            response = self.call(user, method, issue.pk, payload or {"status": "resolved"})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(set(response.data), {"detail"})
            self.assertEqual(str(response.data["detail"]), "No QualityIssue matches the given query.")
            self.assertNotIn("SYNTHETIC_SECRET", response.content.decode())
            self.assertEqual(QualityIssue.objects.filter(pk=issue.pk).values().get(), before)
            self.assertEqual(self.sources(), sources)

    def allowed(self, user, issue, method="patch"):
        sources = self.sources()
        payload = {"status": "acknowledged"}
        if method == "put":
            payload["dimension"] = "metadata"
        response = self.call(user, method, issue.pk, payload)
        self.assertEqual(response.status_code, 200, response.data)
        issue.refresh_from_db()
        self.assertEqual(issue.reviewed_by_id, user.pk)
        self.assertIsNotNone(issue.reviewed_at)
        self.assertEqual(self.sources(), sources)

    def test_f01_anonymous_denied(self):
        issue = self.issue()
        before = list(QualityIssue.objects.values())
        with self.assertNumQueries(0):
            self.assertFalse(quality_issue_queryset({}, user=None).exists())
            self.assertFalse(quality_issue_queryset({}, user=AnonymousUser()).exists())
            for method, pk in (("get", None), ("put", issue.pk), ("patch", issue.pk)):
                response = self.call(None, method, pk, {"status": "resolved"})
                self.assertEqual(response.status_code, 403)
                self.assertEqual(set(response.data), {"detail"})
        self.assertEqual(list(QualityIssue.objects.values()), before)

    def test_f02_shared_native_audit_issues(self):
        run_quality_audit()
        issues = list(QualityIssue.objects.all())
        self.assertEqual({(i.object_type, i.dimension) for i in issues},
                         {("paper", "metadata"), ("document", "document")})
        for user in (self.owner, self.other, self.staff):
            self.assertEqual(self.ids(user), {i.pk for i in issues})
            for issue in issues:
                for method in ("patch", "put"):
                    with self.subTest(user=user.pk, kind=issue.object_type, method=method):
                        self.allowed(user, issue, method)

    def test_f03_dimensions_do_not_grant_access(self):
        for kind, target in (("paper", self.paper.pk), ("document", self.document.pk),
                             ("experiment", self.project.pk)):
            for dimension in QualityIssue.Dimension.values:
                with self.subTest(kind=kind, dimension=dimension):
                    issue = self.issue(kind, target, dimension=dimension)
                    self.assertIn(issue.pk, self.ids(self.owner))
                    self.allowed(self.owner, issue)
                    self.assertEqual(issue.dimension, dimension)
        issue = self.issue(dimension="completeness")
        self.allowed(self.owner, issue)
        self.assertEqual(issue.dimension, "completeness")
        response = self.call(self.owner, "patch", issue.pk, {"dimension": "completeness"})
        self.assertEqual(response.status_code, 400)

    def test_f04_private_experiment_roles_and_statuses(self):
        for status in QualityIssue.Status.values:
            issue = self.issue(status=status)
            self.assertIn(issue.pk, self.ids(self.owner))
            for user in (self.other, self.staff):
                with self.subTest(status=status, user=user.pk):
                    self.assertNotIn(issue.pk, self.ids(user))
                    self.denied(user, issue)
            self.allowed(self.owner, issue)
            self.allowed(self.owner, issue, "put")

    def test_f05_team_read_is_not_write(self):
        self.project.visibility = "team"
        self.project.save()
        issue = self.issue()
        for user in (self.owner, self.other, self.staff):
            self.assertIn(issue.pk, self.ids(user))
        self.denied(self.other, issue)
        for user in (self.owner, self.staff):
            for method in ("patch", "put"):
                self.allowed(user, issue, method)

    def test_f06_ownerless_projects(self):
        self.project.owner = None
        for visibility in ("private", "team"):
            self.project.visibility = visibility
            self.project.save()
            issue = self.issue()
            for user in (self.other, self.staff):
                self.assertEqual(issue.pk in self.ids(user), visibility == "team")
                if visibility == "team" and user.is_staff:
                    self.allowed(user, issue)
                    self.allowed(user, issue, "put")
                else:
                    self.denied(user, issue)

    def test_f07_unknown_and_missing_material_types(self):
        for kind in ("material_version", "unknown"):
            issue = self.issue(kind, 999999, notes="SYNTHETIC_SECRET")
            for user in (self.owner, self.other, self.staff):
                with self.subTest(kind=kind, user=user.pk):
                    self.assertNotIn(issue.pk, self.ids(user))
                    self.denied(user, issue)

    def test_f08_real_private_version_still_unsupported(self):
        material = Material.objects.create(title="Synthetic material", owner=self.owner, visibility="private")
        version = MaterialVersion.objects.create(material=material, number=1, sha256="a" * 64,
            format="md", size=1, created_by=self.owner)
        issue = self.issue("material_version", version.pk, notes="SYNTHETIC_SECRET")
        before = self.sources()
        for user in (self.owner, self.other, self.staff):
            with self.subTest(user=user.pk):
                self.assertNotIn(issue.pk, self.ids(user))
                self.denied(user, issue)
        self.assertEqual(self.sources(), before)

    def test_f09_aliases_are_not_native_types(self):
        canonical = self.issue()
        for kind in ("experiment_project", "experiment_run", "Experiment", " experiment "):
            issue = self.issue(kind)
            for user in (self.owner, self.other, self.staff):
                with self.subTest(kind=kind, user=user.pk):
                    self.assertNotIn(issue.pk, self.ids(user))
                    self.denied(user, issue)
        self.assertEqual(self.ids(self.owner, {"object_type": " experiment "}), {canonical.pk})
        self.assertEqual(self.ids(self.owner, {"object_type": "Experiment"}), set())

    def test_f10_denial_precedes_payload_validation(self):
        hidden = [self.issue("unknown"), self.issue(), self.issue("paper", 999999)]
        payloads = [{"status": "resolved", "notes": "SYNTHETIC_SECRET"},
                    {"object_type": "paper", "object_id": self.paper.pk, "dimension": "invalid",
                     "score": "invalid", "evidence_json": {"body": "SYNTHETIC_SECRET"}}]
        for issue in hidden:
            for payload in payloads:
                with self.subTest(kind=issue.object_type, payload=payload):
                    self.denied(self.other, issue, payload)
        issue = self.issue("paper", self.paper.pk)
        response = self.call(self.other, "patch", issue.pk, {
            "dimension": "ai_output", "score": -99, "notes": "Synthetic text",
            "evidence_json": {"body": "Synthetic payload"}, "object_type": "unknown", "object_id": 999999})
        self.assertEqual(response.status_code, 200)
        issue.refresh_from_db()
        self.assertEqual((issue.object_type, issue.object_id), ("paper", self.paper.pk))
        self.assertEqual((issue.score, issue.dimension), (-99, "ai_output"))
        self.assertEqual(issue.evidence_json, {"body": "Synthetic payload"})
        self.assertIsNone(issue.reviewed_by_id)

    def test_f11_missing_deleted_targets_and_nullable_metadata(self):
        for kind, model in (("paper", Paper), ("document", Document), ("experiment", ExperimentProject)):
            target = model.objects.create(title=f"Synthetic deleted {kind}", **({"owner": self.owner} if kind == "experiment" else {}))
            orphan = self.issue(kind, target.pk)
            target.delete()
            missing = self.issue(kind, 999999)
            for issue in (orphan, missing):
                for user in (self.owner, self.other, self.staff):
                    with self.subTest(kind=kind, pk=issue.pk, user=user.pk):
                        self.assertNotIn(issue.pk, self.ids(user))
                        self.denied(user, issue)
        reviewer = get_user_model().objects.create_user(username="temporary_reviewer")
        task = TaskRecord.objects.create(task_type="synthetic")
        issue = self.issue("paper", self.paper.pk, source_task=task, reviewed_by=reviewer)
        task.delete()
        reviewer.delete()
        self.assertIn(issue.pk, self.ids(self.other))
        self.allowed(self.other, issue)

    def test_f12_same_id_does_not_cross_types(self):
        paper = Paper.objects.create(pk=700, title="Synthetic collision")
        document = Document.objects.create(pk=700, title="Synthetic collision")
        ExperimentProject.objects.create(pk=700, title="Synthetic collision", owner=self.owner)
        issues = {kind: self.issue(kind, 700) for kind in ("paper", "document", "experiment")}
        self.assertEqual(self.ids(self.other), {issues["paper"].pk, issues["document"].pk})
        paper.delete()
        self.assertEqual(self.ids(self.other), {issues["document"].pk})
        self.denied(self.other, issues["paper"])
        document.delete()
        self.assertEqual(self.ids(self.other), set())
        self.assertEqual(self.ids(self.owner), {issues["experiment"].pk})

    def test_f13_filters_only_narrow_authorized_set(self):
        visible = []
        for status in QualityIssue.Status.values:
            visible.append(self.issue("paper", self.paper.pk, status=status))
            self.issue("unknown", status=status)
            self.issue(status=status)
        expected = {i.pk for i in visible}
        self.assertEqual(self.ids(self.other), expected)
        for value in ("", "not-a-number"):
            self.assertEqual(self.ids(self.other, {"object_id": value}), expected)
        for status, issue in zip(QualityIssue.Status.values, visible):
            self.assertEqual(self.ids(self.other, {"status": status, "object_type": " paper ",
                "object_id": str(self.paper.pk)}), {issue.pk})
        for query in ({"object_type": "unknown"}, {"object_type": "experiment_project"},
                      {"object_id": "999999"}, {"status": "unknown"}):
            self.assertEqual(self.ids(self.other, query), set())

    def page(self, user, number=1):
        paginator = PageNumberPagination()
        paginator.page_size = 2
        request = Request(self.factory.get("/api/quality/issues/", {"page": number}))
        rows = paginator.paginate_queryset(quality_issue_queryset({}, user=user), request)
        return paginator.get_paginated_response(QualityIssueSerializer(rows, many=True).data).data

    def test_f14_counts_and_test_pagination_exclude_hidden_rows(self):
        visible = [self.issue("paper", self.paper.pk) for _ in range(3)]
        before = [self.page(self.other, n) for n in (1, 2)]
        for _ in range(4):
            self.issue("unknown")
            self.issue()
            self.issue("document", 999999)
        self.assertEqual(self.ids(self.other), {i.pk for i in visible})
        self.assertEqual(quality_issue_queryset({}, user=self.other).count(), 3)
        self.assertEqual([self.page(self.other, n) for n in (1, 2)], before)
        self.assertEqual(before[0]["count"], 3)
        self.assertIsNotNone(before[0]["next"])
        self.assertIsNotNone(before[1]["previous"])

    def test_f15_revocation_between_requests(self):
        issue = self.issue()
        self.project.visibility = "team"
        self.project.save()
        self.assertIn(issue.pk, self.ids(self.other))
        self.allowed(self.staff, issue)
        self.project.visibility = "private"
        self.project.save()
        for user in (self.other, self.staff):
            self.assertNotIn(issue.pk, self.ids(user))
            self.denied(user, issue)
        self.project.owner = self.other
        self.project.save()
        self.denied(self.owner, issue)
        self.allowed(self.other, issue)
        self.project.visibility = "team"
        self.project.save()
        self.allowed(self.staff, issue)
        self.staff.is_staff = False
        self.staff.save(update_fields=["is_staff"])
        self.assertIn(issue.pk, self.ids(self.staff))
        self.denied(self.staff, issue)

    def test_f16_recheck_before_save_rejects_injected_changes(self):
        original = QualityIssueDetailView.perform_update
        for action in ("delete", "revoke"):
            for method in ("patch", "put"):
                with self.subTest(action=action, method=method):
                    target = ExperimentProject.objects.create(title="Synthetic race", owner=self.owner, visibility="team")
                    issue = self.issue("experiment", target.pk)
                    before = QualityIssue.objects.filter(pk=issue.pk).values().get()
                    source_after_injection = []

                    def inject(view, serializer):
                        if action == "delete":
                            target.delete()
                        else:
                            target.visibility = "private"
                            target.save(update_fields=["visibility"])
                        source_after_injection.append(self.sources())
                        return original(view, serializer)

                    with patch.object(QualityIssueDetailView, "perform_update", inject):
                        response = self.call(self.staff, method, issue.pk,
                                             {"status": "resolved", "dimension": "metadata"})
                    self.assertEqual(response.status_code, 404)
                    self.assertEqual(str(response.data["detail"]), "No QualityIssue matches the given query.")
                    self.assertEqual(QualityIssue.objects.filter(pk=issue.pk).values().get(), before)
                    self.assertEqual(self.sources(), source_after_injection[0])

    def test_f17_bounded_evaluated_business_queries(self):
        task = TaskRecord.objects.create(task_type="synthetic")
        issue = self.issue("paper", self.paper.pk, source_task=task, reviewed_by=self.owner)
        for size in (1, 100):
            if size == 100:
                QualityIssue.objects.bulk_create([QualityIssue(object_type="paper", object_id=self.paper.pk,
                    dimension="metadata", source_task=task, reviewed_by=self.owner) for _ in range(99)])
            with CaptureQueriesContext(connection) as queries:
                response = self.call(self.other)
                self.assertEqual(len(response.data), size)
            self.assertEqual(len(queries), 1)
            sql = queries[0]["sql"]
            for table in ("papers_paper", "documents_document", "experiments_experimentproject"):
                self.assertIn(table, sql)
            for kind in ("paper", "document", "experiment"):
                self.assertIn(f"= '{kind}'", sql)
            self.assertGreaterEqual(sql.upper().count(" IN (SELECT "), 3)
            with CaptureQueriesContext(connection) as queries:
                data = self.page(self.other)
                self.assertEqual(data["count"], size)
            self.assertEqual(len(queries), 2)
        sources = self.sources()
        for method in ("patch", "put"):
            with CaptureQueriesContext(connection) as queries:
                response = self.call(self.other, method, issue.pk,
                                     {"status": "resolved", "dimension": "metadata"})
                self.assertEqual(response.status_code, 200)
            self.assertEqual(len(queries), 3)
            self.assertEqual([q["sql"].split()[0] for q in queries], ["SELECT", "SELECT", "UPDATE"])
            for query in queries[:2]:
                for table in ("papers_paper", "documents_document", "experiments_experimentproject"):
                    self.assertIn(table, query["sql"])
            self.assertEqual(self.sources(), sources)

    def test_f18_methods_and_readonly_anchors_stay_compatible(self):
        issue = self.issue("paper", self.paper.pk)
        hidden = self.issue("unknown")
        sources = self.sources()
        for pk in (issue.pk, hidden.pk, 999999):
            self.assertEqual(self.call(self.other, "get", pk).status_code, 405)
            self.assertEqual(self.call(self.other, "delete", pk).status_code, 405)
        self.assertEqual(self.call(self.other, "post").status_code, 405)
        for method in ("patch", "put"):
            response = self.call(self.other, method, issue.pk, {
                "object_type": "unknown", "object_id": 999999, "dimension": "metadata", "status": "resolved"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(set(response.data), set(QualityIssueSerializer.Meta.fields))
            issue.refresh_from_db()
            self.assertEqual((issue.object_type, issue.object_id), ("paper", self.paper.pk))
        self.assertEqual(self.sources(), sources)
