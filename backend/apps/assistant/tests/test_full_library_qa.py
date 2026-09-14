"""全库问答基线；私有题集显式启用，科研质量不以测试执行成功代替。"""
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.assistant.agent import run_exchange
from apps.assistant.knowledge import search_knowledge
from apps.assistant.models import AssistantExchange, AssistantSession
from apps.materials.models import Evidence, Material, MaterialVersion
from apps.papers.models import Paper


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def validate_dataset(data):
    if data.get("schema_version") != 1:
        raise ValueError("不支持的题集版本")
    records, cases = data["records"], data["cases"]
    keys = [r["key"] for r in records]
    if len(keys) != len(set(keys)) or not keys:
        raise ValueError("材料标识缺失或重复")
    case_ids = [c["id"] for c in cases]
    if len(case_ids) != len(set(case_ids)) or not case_ids:
        raise ValueError("问题标识缺失或重复")
    for record in records:
        if record["kind"] not in {"material", "paper"}:
            raise ValueError("不支持的夹具来源")
        if not record.get("source_kind") or not record.get("title"):
            raise ValueError("缺少来源身份")
        if record.get("owner", "self") not in {"self", "other"}:
            raise ValueError("未知所有者")
        if record.get("visibility", "team") not in {"team", "private"}:
            raise ValueError("未知可见性")
        if record["kind"] == "material" and not record.get("chunks"):
            raise ValueError("材料没有证据")
    for case in cases:
        if case.get("scope", {}) != {}:
            raise ValueError("全库题不得预选材料")
        if case.get("split") not in {"baseline", "holdout"}:
            raise ValueError("必须声明基线或保留题")
        if not case.get("question") or "forbidden_claims" not in case:
            raise ValueError("缺少问题或质量门禁")
        for group in case["required_groups"]:
            if not group or any(key not in keys for key in group):
                raise ValueError("金标指向未知来源")
            if any(next(r for r in records if r["key"] == key).get("visibility") == "private"
                   and next(r for r in records if r["key"] == key).get("owner") == "other" for key in group):
                raise ValueError("金标不能要求读取他人私密内容")
    return data


def group_recall(groups, retrieved):
    if not groups:
        return None
    return sum(bool(set(group) & set(retrieved)) for group in groups) / len(groups)


def excerpt_coverage(groups, trace, refs):
    """金标短语仅用于计分；命中文章不等于实际看到必要的论据。"""
    if not groups:
        return None
    def normalized(text):
        return "".join(text.casefold().split())
    seen = [(refs[(s["type"], s["id"])], normalized(s["excerpt"]))
            for row in trace for s in row["sources"]]
    return sum(any(key == item["key"] and normalized(item["contains"]) in text
                   for item in group for key, text in seen) for group in groups) / len(groups)


def seed_dataset(data, user, other):
    """仅供 Django 隔离 TestCase；不执行生产迁移或上传。"""
    refs = {}
    for record in data["records"]:
        if record["kind"] == "paper":
            row = Paper.objects.create(title=record["title"], abstract=record.get("abstract", ""))
            refs[("paper", row.pk)] = record["key"]
            continue
        owner = other if record.get("owner") == "other" else user
        material = Material.objects.create(title=record["title"], owner=owner,
                                           visibility=record.get("visibility", "team"), source_kind=record["source_kind"])
        for number, chunks in enumerate(record.get("versions", [record["chunks"]]), 1):
            version = MaterialVersion.objects.create(material=material, number=number,
                sha256=digest(chunks), filename="fixture.md", format="md", size=1,
                status="needs_review" if record.get("format") == "pdf" else "ready", created_by=owner)
            for ordinal, text in enumerate(chunks, 1):
                evidence = Evidence.objects.create(version=version, ordinal=ordinal, text=text,
                    page=ordinal if record.get("format") == "pdf" else None,
                    line_start=None if record.get("format") == "pdf" else ordinal,
                    line_end=None if record.get("format") == "pdf" else ordinal,
                    review_required=record.get("format") == "pdf")
                refs[("material", evidence.pk)] = record["key"]
    return refs


def measure_case(case, refs, user, model_call=None):
    """测量现有工具循环，不注入检索词、金标或答案，不改变生产逻辑。"""
    from apps.ai.minimax import call_minimax_chat
    real_call = model_call or call_minimax_chat
    from apps.assistant.reading import read_source, find_in_source
    trace, readings, transmitted, transmitted_sources = [], [], [], []
    def retrieve(actor, scope, query, **kwargs):
        rows = search_knowledge(actor, scope, query, **kwargs)
        trace.append({"query": query, "queries": kwargs.get("queries", []), "keys": list(dict.fromkeys(refs[(r["type"], r["id"])] for r in rows)),
                      "sources": rows})
        return rows
    def read(actor, scope, source, **kwargs):
        result = read_source(actor, scope, source, **kwargs)
        readings.append({"source_ref": source.get("label"), "options": kwargs, "sources": result["sources"]})
        return result
    def locate(actor, scope, source, **kwargs):
        result = find_in_source(actor, scope, source, **kwargs)
        readings.append({'tool': 'find_in_source', 'source_ref': source.get('label'), 'options': kwargs, 'sources': result['sources']})
        return result
    def transport(messages, **kwargs):
        # 只保留实际工具证据；不落盘隐藏推理或完整请求。
        for message in messages:
            if message.get("role") == "tool":
                transmitted.append(message.get("content", ""))
                transmitted_sources.extend(json.loads(message["content"]).get("sources", []))
        return real_call(messages, **kwargs)
    session = AssistantSession.objects.create(created_by=user, title="全库基线", scope_json={})
    exchange = AssistantExchange.objects.create(session=session, question=case["question"],
                                                status="queued", request_id=uuid.uuid4())
    start = time.monotonic()
    with patch("apps.assistant.agent.search_knowledge", side_effect=retrieve), \
         patch("apps.assistant.agent.read_source", side_effect=read), \
         patch("apps.assistant.agent.find_in_source", side_effect=locate), \
         patch("apps.assistant.agent.call_minimax_chat", side_effect=transport):
        run_exchange(exchange.pk, 1)
    exchange.refresh_from_db()
    retrieved = list(dict.fromkeys(key for row in trace for key in row["keys"]))
    cited = list(dict.fromkeys(refs[(r["type"], r["id"])] for r in exchange.sources))
    return {"id": case["id"], "question": case["question"], "scope": session.scope_json,
            "status": exchange.status, "seconds": round(time.monotonic() - start, 2),
            "answer": exchange.answer, "error": exchange.error, "usage": exchange.usage,
            "retrieval": trace, "readings": readings, "transmitted_sources": transmitted_sources,
            "required_transmitted_excerpt_coverage": excerpt_coverage(case.get("required_excerpt_groups", []), [{"sources": transmitted_sources}], refs),
            "retrieved_keys": retrieved, "cited_keys": cited,
            "required_group_recall": group_recall(case["required_groups"], retrieved),
            "required_excerpt_coverage": excerpt_coverage(case.get("required_excerpt_groups", []), trace, refs),
            "cited_group_coverage": group_recall(case["required_groups"], cited),
            "private_sentinel_exposed": "PRIVATE_BASELINE_SENTINEL" in (exchange.answer + "".join(transmitted)),
            "quality_status": "pending_human_review"}


class FullLibraryBaselineTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="baseline-self")
        self.other = get_user_model().objects.create_user(username="baseline-other")
        self.data = {"schema_version": 1, "records": [
            {"key": "target", "kind": "material", "source_kind": "human_record", "title": "合成网格记录",
             "chunks": ["mesh synthetic source fact"]},
            {"key": "noise", "kind": "material", "source_kind": "human_record", "title": "无关合成记录",
             "chunks": ["crystal synthetic material"]},
            {"key": "private", "kind": "material", "source_kind": "human_record", "title": "mesh private",
             "owner": "other", "visibility": "private", "chunks": ["mesh PRIVATE_BASELINE_SENTINEL"]}],
            "cases": [{"id": "case", "question": "mesh 有什么依据？", "split": "baseline",
                       "required_groups": [["target"]], "forbidden_claims": ["合成内容冒充论文"]}]}

    def test_manifest_rejects_prescoped_questions(self):
        self.data["cases"][0]["scope"] = {"material_ids": [1]}
        with self.assertRaises(ValueError):
            validate_dataset(self.data)

    def test_manifest_rejects_unknown_gold_and_private_gold(self):
        for key in ["missing", "private"]:
            self.data["cases"][0]["required_groups"] = [[key]]
            with self.assertRaises(ValueError):
                validate_dataset(self.data)

    def test_alternative_evidence_groups_are_not_double_counted(self):
        self.assertEqual(group_recall([["a", "b"], ["c"]], ["a", "b"]), 0.5)
        self.assertIsNone(group_recall([], []))

    def test_material_hit_does_not_imply_required_excerpt_seen(self):
        refs = {("material", 1): "paper"}
        trace = [{"sources": [{"type": "material", "id": 1, "excerpt": "abstract only"}]}]
        groups = [[{"key": "paper", "contains": "method limitation"}]]
        self.assertEqual(excerpt_coverage(groups, trace, refs), 0)

    def test_default_scope_searches_mixed_library_and_excludes_private(self):
        refs = seed_dataset(validate_dataset(self.data), self.user, self.other)
        rows = search_knowledge(self.user, {}, "mesh")
        self.assertEqual([refs[(r["type"], r["id"])] for r in rows], ["target"])

    def test_measurement_keeps_gold_out_of_model_and_does_not_claim_quality(self):
        from apps.assistant.tests.test_agent import reply, search
        refs = seed_dataset(self.data, self.user, self.other)
        calls = []
        responses = iter([search("mesh"), reply({"answer": "合成记录 [S1]"}), reply({"answer": "合成记录 [S1]"})])
        def model(messages, **kwargs):
            calls.append(json.dumps(messages, ensure_ascii=False))
            return next(responses)
        report = measure_case(self.data["cases"][0], refs, self.user, model)
        self.assertEqual(report["scope"], {})
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["required_group_recall"], 1)
        self.assertFalse(report["private_sentinel_exposed"])
        self.assertEqual(report["quality_status"], "pending_human_review")
        self.assertNotIn("forbidden_claims", "".join(calls))
        self.assertNotIn("required_groups", "".join(calls))


@skipUnless(os.getenv("RWV_FULL_LIBRARY_BASELINE") == "1", "需显式启用服务器私有基线")
class FullLibraryLiveBaselineTests(TestCase):
    def test_record_frozen_baseline(self):
        self.assertTrue(os.environ.get("POSTGRES_DB", "").startswith("rwv_m6a_"), "必须使用专用基线数据库")
        raw = Path(os.environ["RWV_BASELINE_DATASET"]).read_bytes()
        data = validate_dataset(json.loads(raw))
        self.assertEqual(hashlib.sha256(raw).hexdigest(), os.environ["RWV_BASELINE_SHA256"])
        user = get_user_model().objects.create_user(username="live-baseline-self")
        other = get_user_model().objects.create_user(username="live-baseline-other")
        refs = seed_dataset(data, user, other)
        output = Path(os.environ["RWV_BASELINE_REPORT"])
        # 拒绝覆盖已有基线；每题完成立即落盘，失败也留证。
        with output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps({"dataset_sha256": hashlib.sha256(raw).hexdigest(),
                "commit": os.environ["RWV_BASELINE_COMMIT"], "holdout_executed": False,
                "fixture_layer": "retrieval_not_upload", "quality_gate": "not_evaluated"}) + "\n")
            results = []
            for case in data["cases"]:
                if case["split"] != "baseline":
                    continue
                report = measure_case(case, refs, user)
                results.append(report)
                stream.write(json.dumps(report, ensure_ascii=False) + "\n")
                stream.flush()
                print(json.dumps({k: report[k] for k in ("id", "status", "seconds", "required_group_recall", "usage")}), flush=True)
        self.assertTrue(results)
        self.assertFalse(any(r["private_sentinel_exposed"] for r in results))
        # 此测试证明记录器跑完，不把答案质量或调用成功率变成通过断言。
