from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.materials.models import Material, MaterialVersion, Evidence


class EvidenceSearchTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="evidence-owner")
        self.other = get_user_model().objects.create_user(username="evidence-other")
        self.client.force_login(self.owner)

    def source(self, text="Fourier neural operator convergence", visibility="team", title="算子学习"):
        material = Material.objects.create(title=title, owner=self.owner, visibility=visibility)
        version = MaterialVersion.objects.create(material=material, number=1, sha256="a" * 64,
            filename="paper.pdf", format="pdf", size=10, storage_key="unused.pdf", status="needs_review", created_by=self.owner)
        evidence = Evidence.objects.create(version=version, ordinal=1, page=3, text=text, review_required=True)
        return material, version, evidence

    def search(self, query, **params):
        return self.client.get("/api/search/evidence/", {"q": query, **params})

    def test_evidence_contains_exact_source_and_review_status(self):
        material, version, evidence = self.source()
        response = self.search("Fourier operator")
        self.assertEqual(response.status_code, 200)
        result = response.json()["results"][0]
        self.assertEqual(result["evidence_id"], evidence.pk)
        self.assertEqual(result["version_id"], version.pk)
        self.assertEqual(result["page"], 3)
        self.assertTrue(result["review_required"])
        self.assertEqual(result["file_url"], f"/api/materials/{material.pk}/versions/{version.pk}/file/#page=3")
        self.assertNotIn("storage_key", result)
        self.assertEqual(response.json()["mode"], "keyword")
        self.assertIn("no-store", response["Cache-Control"])

    def test_private_scope_and_revocation_apply_without_reindex(self):
        material, _, _ = self.source()
        self.client.force_login(self.other)
        self.assertEqual(len(self.search("Fourier").json()["results"]), 1)
        material.visibility = "private"
        material.save()
        self.assertEqual(self.search("Fourier").json()["results"], [])
        self.assertEqual(self.search("Fourier", material_id=material.pk).status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(len(self.search("Fourier").json()["results"]), 1)
        self.client.logout()
        self.assertIn(self.search("Fourier").status_code, (401, 403))

    def test_only_latest_usable_version_and_deletion_are_live(self):
        material, old, _ = self.source("old convergence result")
        new = MaterialVersion.objects.create(material=material, number=2, sha256="b" * 64,
            filename="new.md", format="md", size=10, storage_key="unused.md", status="failed", created_by=self.owner)
        self.assertEqual(len(self.search("old convergence").json()["results"]), 1)
        Evidence.objects.create(version=new, ordinal=1, line_start=1, line_end=2, text="new convergence result")
        new.status = "ready"
        new.save()
        results = self.search("convergence").json()["results"]
        self.assertEqual([row["version_id"] for row in results], [new.pk])
        self.assertEqual(old.evidence.count(), 1)
        material.delete()
        self.assertEqual(self.search("convergence").json()["results"], [])

    def test_chinese_and_english_ranking(self):
        exact, _, _ = self.source("神经算子在偏微分方程中的泛化误差")
        self.source("算子学习概览")
        self.assertEqual(self.search("神经算子").json()["results"][0]["material_id"], exact.pk)
        stronger, _, _ = self.source("PINN boundary condition error")
        self.source("PINN introduction")
        self.assertEqual(self.search("PINN boundary").json()["results"][0]["material_id"], stronger.pk)

    def test_source_coverage_limits_repeated_pages(self):
        _, version, _ = self.source()
        for number in range(2, 12):
            Evidence.objects.create(version=version, ordinal=number, page=number, text="Fourier neural operator convergence")
        other, _, _ = self.source("Fourier comparison")
        results = self.search("Fourier", limit=5).json()["results"]
        self.assertIn(other.pk, [row["material_id"] for row in results])
        self.assertLessEqual(sum(row["version_id"] == version.pk for row in results), 2)

    def test_empty_query_and_invalid_filters_do_not_dump_corpus(self):
        self.source()
        for query in ["", " ", "!!!", "a" * 501]:
            self.assertEqual(self.search(query).status_code, 400)
        self.assertEqual(self.search("Fourier", limit="invalid").status_code, 400)
        self.assertEqual(self.search("Fourier", material_id="invalid").status_code, 400)

    def test_match_near_end_of_page_is_in_excerpt(self):
        self.source("intro " * 400 + "BOUNDARY discrepancy conclusion")
        result = self.search("boundary").json()["results"][0]
        self.assertIn("BOUNDARY", result["excerpt"])
        self.assertLessEqual(len(result["excerpt"]), 603)

    def test_hybrid_request_is_explicitly_downgraded(self):
        self.source()
        response = self.search("Fourier", mode="hybrid").json()
        self.assertEqual(response["mode"], "keyword")
        self.assertTrue(response["degraded"])
        self.assertTrue(response["notice"])
