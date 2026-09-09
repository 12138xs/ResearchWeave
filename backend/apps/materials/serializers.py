from rest_framework import serializers


class UploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    title = serializers.CharField(max_length=500, required=False, default="", allow_blank=True)
    visibility = serializers.ChoiceField(choices=["team", "private"], default="team")


class CardSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=300)
    markdown = serializers.CharField(max_length=100_000)
    evidence_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=1, max_length=100)


