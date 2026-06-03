from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.documents.models import Document
from apps.library.models import KnowledgeSpace


class KnowledgeSpaceApiTests(TestCase):
    def test_knowledge_space_path_and_descendants(self) -> None:
        root = KnowledgeSpace.objects.create(name="Deep Learning", kind="docs", order=1)
        child = KnowledgeSpace.objects.create(name="Transformer", kind="docs", parent=root, order=1)
        leaf = KnowledgeSpace.objects.create(name="Attention", kind="docs", parent=child, order=1)

        response = self.client.get("/api/knowledge-spaces/?kind=docs")

        self.assertEqual(response.status_code, 200)
        by_id = {item["id"]: item for item in response.json()}
        self.assertEqual(by_id[root.id]["path"], "Deep Learning")
        self.assertEqual(by_id[child.id]["path"], "Deep Learning / Transformer")
        self.assertEqual(by_id[leaf.id]["path"], "Deep Learning / Transformer / Attention")
        self.assertEqual(by_id[root.id]["depth"], 0)
        self.assertEqual(by_id[leaf.id]["depth"], 2)
        self.assertEqual(by_id[root.id]["descendant_count"], 2)

    def test_move_rejects_cycles(self) -> None:
        root = KnowledgeSpace.objects.create(name="Deep Learning", kind="docs")
        child = KnowledgeSpace.objects.create(name="Transformer", kind="docs", parent=root)

        response = self.client.post(
            f"/api/knowledge-spaces/{root.id}/move/",
            {"parent_id": child.id},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("cycle", response.json()["detail"].lower())

    def test_move_rejects_negative_order(self) -> None:
        space = KnowledgeSpace.objects.create(name="Deep Learning", kind="docs")

        response = self.client.post(
            f"/api/knowledge-spaces/{space.id}/move/",
            {"order": -1},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("order", response.json()["detail"].lower())

    def test_move_rejects_non_integer_order(self) -> None:
        space = KnowledgeSpace.objects.create(name="Deep Learning", kind="docs")

        for value in (1.2, True, "abc", "1.2"):
            with self.subTest(order=value):
                response = self.client.post(
                    f"/api/knowledge-spaces/{space.id}/move/",
                    {"order": value},
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 400)
                self.assertIn("order", response.json()["detail"].lower())

    def test_move_rejects_invalid_parent_id(self) -> None:
        space = KnowledgeSpace.objects.create(name="Deep Learning", kind="docs")

        for value in ("abc", True):
            with self.subTest(parent_id=value):
                response = self.client.post(
                    f"/api/knowledge-spaces/{space.id}/move/",
                    {"parent_id": value},
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 400)
                self.assertIn("parent_id", response.json()["detail"].lower())

    def test_move_parent_id_null_moves_space_to_root(self) -> None:
        root = KnowledgeSpace.objects.create(name="Deep Learning", kind="docs")
        child = KnowledgeSpace.objects.create(name="Transformer", kind="docs", parent=root)

        response = self.client.post(
            f"/api/knowledge-spaces/{child.id}/move/",
            {"parent_id": None},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        child.refresh_from_db()
        self.assertIsNone(child.parent)
        self.assertIsNone(response.json()["parent_id"])

    def test_move_parent_id_empty_string_moves_space_to_root(self) -> None:
        root = KnowledgeSpace.objects.create(name="Deep Learning", kind="docs")
        child = KnowledgeSpace.objects.create(name="Transformer", kind="docs", parent=root)

        response = self.client.post(
            f"/api/knowledge-spaces/{child.id}/move/",
            {"parent_id": ""},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        child.refresh_from_db()
        self.assertIsNone(child.parent)
        self.assertIsNone(response.json()["parent_id"])

    def test_move_parent_id_moves_space_to_active_parent(self) -> None:
        root_a = KnowledgeSpace.objects.create(name="Deep Learning", kind="docs")
        root_b = KnowledgeSpace.objects.create(name="Numerics", kind="docs")
        child = KnowledgeSpace.objects.create(name="Transformer", kind="docs", parent=root_a)

        response = self.client.post(
            f"/api/knowledge-spaces/{child.id}/move/",
            {"parent_id": root_b.id},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        child.refresh_from_db()
        self.assertEqual(child.parent, root_b)
        self.assertEqual(response.json()["parent_id"], root_b.id)

    def test_move_without_parent_id_keeps_existing_parent_and_updates_order(self) -> None:
        root = KnowledgeSpace.objects.create(name="Deep Learning", kind="docs")
        child = KnowledgeSpace.objects.create(name="Transformer", kind="docs", parent=root, order=1)

        response = self.client.post(
            f"/api/knowledge-spaces/{child.id}/move/",
            {"order": 5},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        child.refresh_from_db()
        self.assertEqual(child.parent, root)
        self.assertEqual(child.order, 5)
        self.assertEqual(response.json()["parent_id"], root.id)

    def test_detail_get_returns_single_space(self) -> None:
        space = KnowledgeSpace.objects.create(
            name="Deep Learning",
            kind="docs",
            description="Original description",
        )

        response = self.client.get(f"/api/knowledge-spaces/{space.id}/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["id"], space.id)
        self.assertEqual(payload["name"], "Deep Learning")
        self.assertEqual(payload["description"], "Original description")

    def test_detail_patch_updates_space(self) -> None:
        space = KnowledgeSpace.objects.create(
            name="Deep Learning",
            kind="docs",
            description="Original description",
        )

        response = self.client.patch(
            f"/api/knowledge-spaces/{space.id}/",
            {"name": "Neural Operators", "description": "Updated description"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["name"], "Neural Operators")
        self.assertEqual(payload["description"], "Updated description")
        space.refresh_from_db()
        self.assertEqual(space.name, "Neural Operators")
        self.assertEqual(space.description, "Updated description")

    def test_detail_patch_does_not_update_is_active(self) -> None:
        space = KnowledgeSpace.objects.create(name="Deep Learning", kind="docs", is_active=True)

        response = self.client.patch(
            f"/api/knowledge-spaces/{space.id}/",
            {"is_active": False},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        space.refresh_from_db()
        self.assertIs(space.is_active, True)
        self.assertIs(response.json()["is_active"], True)

    def test_archive_marks_space_inactive(self) -> None:
        space = KnowledgeSpace.objects.create(name="Old Notes", kind="docs", is_active=True)

        response = self.client.post(f"/api/knowledge-spaces/{space.id}/archive/")

        self.assertEqual(response.status_code, 200)
        space.refresh_from_db()
        self.assertIs(space.is_active, False)

    def test_archive_marks_descendants_inactive_and_hides_them_from_list(self) -> None:
        root = KnowledgeSpace.objects.create(name="Deep Learning", kind="docs")
        child = KnowledgeSpace.objects.create(name="Transformer", kind="docs", parent=root)
        leaf = KnowledgeSpace.objects.create(name="Attention", kind="docs", parent=child)

        response = self.client.post(f"/api/knowledge-spaces/{root.id}/archive/")

        self.assertEqual(response.status_code, 200)
        root.refresh_from_db()
        child.refresh_from_db()
        leaf.refresh_from_db()
        self.assertIs(root.is_active, False)
        self.assertIs(child.is_active, False)
        self.assertIs(leaf.is_active, False)

        list_response = self.client.get("/api/knowledge-spaces/?kind=docs")

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json(), [])


class NormalizeKnowledgeSpacesCommandTests(TestCase):
    def test_dry_run_identifies_source_like_spaces(self) -> None:
        KnowledgeSpace.objects.create(name="\u98de\u4e66\u8d44\u6599", kind=KnowledgeSpace.Kind.DOCS)
        KnowledgeSpace.objects.create(name="Numerics", kind=KnowledgeSpace.Kind.DOCS)
        out = StringIO()

        call_command("normalize_knowledge_spaces", "--dry-run", stdout=out)

        output = out.getvalue()
        self.assertIn("\u98de\u4e66\u8d44\u6599", output)
        self.assertIn("source/import is not a knowledge category", output)
        self.assertNotIn("Numerics", output)

    def test_apply_moves_source_like_space_documents_to_active_parent(self) -> None:
        parent = KnowledgeSpace.objects.create(name="PDE", kind=KnowledgeSpace.Kind.DOCS)
        source = KnowledgeSpace.objects.create(name="Feishu imports", kind=KnowledgeSpace.Kind.DOCS, parent=parent)
        document = Document.objects.create(title="Imported PDE Notes", space=source)
        out = StringIO()

        call_command("normalize_knowledge_spaces", "--apply", stdout=out)

        document.refresh_from_db()
        source.refresh_from_db()
        parent.refresh_from_db()
        self.assertEqual(document.space, parent)
        self.assertIs(source.is_active, False)
        self.assertIs(parent.is_active, True)

    def test_apply_moves_root_source_like_space_documents_to_ungrouped(self) -> None:
        source = KnowledgeSpace.objects.create(name="\u5bfc\u5165", kind=KnowledgeSpace.Kind.DOCS)
        document = Document.objects.create(title="Imported Notes", space=source)
        out = StringIO()

        call_command("normalize_knowledge_spaces", "--apply", stdout=out)

        document.refresh_from_db()
        source.refresh_from_db()
        self.assertIsNone(document.space)
        self.assertIs(source.is_active, False)

    def test_apply_moves_source_like_space_with_inactive_parent_to_ungrouped(self) -> None:
        parent = KnowledgeSpace.objects.create(name="Numerics", kind=KnowledgeSpace.Kind.DOCS, is_active=False)
        source = KnowledgeSpace.objects.create(name="Lark", kind=KnowledgeSpace.Kind.DOCS, parent=parent)
        document = Document.objects.create(title="Imported Numerics Notes", space=source)
        out = StringIO()

        call_command("normalize_knowledge_spaces", "--apply", stdout=out)

        document.refresh_from_db()
        source.refresh_from_db()
        self.assertIsNone(document.space)
        self.assertIs(source.is_active, False)

    def test_apply_moves_nested_source_like_documents_to_nearest_category_ancestor(self) -> None:
        category = KnowledgeSpace.objects.create(name="Claude Code", kind=KnowledgeSpace.Kind.DOCS)
        source_root = KnowledgeSpace.objects.create(name="飞书", kind=KnowledgeSpace.Kind.DOCS, parent=category)
        source_package = KnowledgeSpace.objects.create(
            name="Mark 的 AI 产品经理知识库",
            kind=KnowledgeSpace.Kind.DOCS,
            parent=source_root,
        )
        source_leaf = KnowledgeSpace.objects.create(name="二级正文页", kind=KnowledgeSpace.Kind.DOCS, parent=source_package)
        document = Document.objects.create(title="Nested Imported Notes", space=source_leaf)
        out = StringIO()

        call_command("normalize_knowledge_spaces", "--apply", stdout=out)

        document.refresh_from_db()
        source_root.refresh_from_db()
        source_package.refresh_from_db()
        source_leaf.refresh_from_db()
        category.refresh_from_db()
        self.assertEqual(document.space, category)
        self.assertIs(category.is_active, True)
        self.assertIs(source_root.is_active, False)
        self.assertIs(source_package.is_active, False)
        self.assertIs(source_leaf.is_active, False)

    def test_apply_does_not_archive_real_category_spaces(self) -> None:
        categories = [
            KnowledgeSpace.objects.create(name=name, kind=KnowledgeSpace.Kind.DOCS)
            for name in ("Numerics", "PDE", "Deep Learning", "Transformer", "Important Methods")
        ]
        documents = [Document.objects.create(title=f"{space.name} Notes", space=space) for space in categories]
        out = StringIO()

        call_command("normalize_knowledge_spaces", "--apply", stdout=out)

        for space in categories:
            space.refresh_from_db()
            self.assertIs(space.is_active, True)
        for document, space in zip(documents, categories, strict=True):
            document.refresh_from_db()
            self.assertEqual(document.space, space)
