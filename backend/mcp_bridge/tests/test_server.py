import unittest

from mcp import Client

from researchweave_mcp.server import create_server


class FakeClient:
    def search_materials(self, query=""):
        return {"results": [{"material_id": 1, "title": query}], "truncated": False}

    def get_material(self, material_id):
        return {"material_id": material_id, "source_kind": "human_record"}

    def search_evidence(self, query, *, limit=10, material_id=None):
        return {"results": [{"query": query, "limit": limit, "material_id": material_id}]}

    def build_context_bundle(self, question, *, material_ids=None, limit=10):
        return {"bundle_id": "rcb_test", "question": question, "material_ids": material_ids or [], "limit": limit}

    def get_context_bundle(self, bundle_id):
        return {"bundle_id": bundle_id, "content_digest": "sha256:test"}


class ServerContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_capability_probe_limits_discovered_tools(self):
        server = create_server(FakeClient(), ["materials.list"])
        async with Client(server) as client:
            tools = await client.list_tools()
            self.assertEqual([tool.name for tool in tools.tools], ["search_materials"])
            self.assertTrue(tools.tools[0].annotations.read_only_hint)
            result = await client.call_tool("search_materials", {"query": "FNO"})
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["results"][0]["title"], "FNO")

    async def test_all_read_only_tools_round_trip_through_mcp(self):
        capabilities = [
            "materials.list",
            "materials.get",
            "evidence.search",
            "context_bundles.build",
            "context_bundles.get",
        ]
        server = create_server(FakeClient(), capabilities)
        async with Client(server) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            self.assertEqual(names, {
                "search_materials",
                "get_material",
                "search_evidence",
                "build_context_bundle",
                "get_context_bundle",
            })
            built = await client.call_tool("build_context_bundle", {
                "question": "compare operators",
                "material_ids": [1, 2],
                "limit": 5,
            })
            fetched = await client.call_tool("get_context_bundle", {"bundle_id": "rcb_test"})
        self.assertEqual(built.structured_content["bundle_id"], "rcb_test")
        self.assertEqual(fetched.structured_content["content_digest"], "sha256:test")
