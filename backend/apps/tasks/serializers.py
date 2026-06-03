from __future__ import annotations

from rest_framework import serializers

from apps.tasks.models import TaskRecord


TASK_LABELS = {
    "paper_upload_postprocess": "论文上传后处理",
    "deep_process_paper": "论文深读处理",
    "paper_light_process": "论文轻读概览",
    "paper_ai_light_process": "AI 轻读概览",
    "document_import_candidates": "文档导入候选生成",
    "apps.documents.tasks.generate_document_import_candidates": "文档导入候选生成",
    "experiment_run_execute": "实验运行记录",
    "search_reindex": "统一检索重建",
    "quality_audit": "质量审计",
    "direction_map_generate": "方向地图生成",
    "fast_ping": "快速队列检查",
    "ai_ping": "AI 队列检查",
    "heavy_ping": "重型队列检查",
}


class TaskRecordSerializer(serializers.ModelSerializer):
    label = serializers.SerializerMethodField()

    class Meta:
        model = TaskRecord
        fields = [
            "id",
            "task_type",
            "label",
            "status",
            "progress",
            "stage",
            "object_type",
            "object_id",
            "result",
            "error",
            "created_at",
            "updated_at",
        ]

    def get_label(self, obj: TaskRecord) -> str:
        return TASK_LABELS.get(obj.task_type, obj.task_type.replace("_", " "))
