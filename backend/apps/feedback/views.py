import re

from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Feedback

# Mentions identify product areas, never members or notifications.
FEATURES = [
    {"key": key, "label": label, "path": path}
    for key, label, path in [
        ("agent", "内置科研Agent", "/agent"),
        ("materials", "研究材料", "/materials"),
        ("papers", "论文库", "/papers"),
        ("reading", "论文阅读", "/papers"),
        ("documents", "知识文档", "/docs"),
        ("experiments", "实验日志", "/experiments"),
        ("search", "统一检索", "/search"),
        ("quality", "质量治理", "/quality"),
        ("spaces", "知识体系", "/knowledge-spaces"),
        ("tasks", "任务队列", "/tasks"),
        ("settings", "系统设置", "/settings"),
        ("feedback", "意见箱", "/feedback"),
    ]
]


def mentioned_features(content):
    return [item["key"] for item in FEATURES if re.search(
        r"(?<![\w@])@" + re.escape(item["label"]) + r"(?=$|[\s，。！？；：、,.!?;:])", content
    )]


class InputSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=4000, allow_blank=False)
    request_id = serializers.UUIDField()


class FeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feedback
        fields = ["id", "author_name", "content", "features", "created_at"]


class FeedbackList(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        raw = request.query_params.get("page", "1")
        if not re.fullmatch(r"[0-9]{1,7}", raw) or int(raw) < 1:
            return Response({"detail": "页码无效。"}, status=400)
        page = int(raw)
        queryset = Feedback.objects.all()
        count = queryset.count()
        return Response({"count": count, "page": page, "page_size": 20,
                         "catalog": FEATURES,
                         "results": FeedbackSerializer(queryset[(page - 1) * 20:page * 20], many=True).data})

    def post(self, request):
        data = InputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        content = data.validated_data["content"]
        feedback, created = Feedback.objects.get_or_create(
            request_id=data.validated_data["request_id"],
            defaults={"author": request.user, "author_name": request.user.get_username(),
                      "content": content, "features": mentioned_features(content)},
        )
        if not created and (feedback.author_id != request.user.pk or feedback.content != content):
            return Response({"detail": "提交标识已使用，请刷新页面后重试。"}, status=409)
        return Response(FeedbackSerializer(feedback).data,
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
