from django.utils import timezone
from rest_framework import serializers
from .models import CheatingReport, CheatingEvidence


class CheatingEvidenceSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = CheatingEvidence
        fields = [
            "id", "evidence_type", "description",
            "file", "file_url",
            "uploaded_by", "uploaded_by_name", "created_at",
        ]
        read_only_fields = ["id", "uploaded_by", "uploaded_by_name", "file_url", "created_at"]
        extra_kwargs = {"file": {"write_only": True}}

    def get_uploaded_by_name(self, obj):
        if obj.uploaded_by:
            return obj.uploaded_by.get_full_name() or obj.uploaded_by.username
        return None

    def get_file_url(self, obj):
        return obj.file_url


class CheatingReportListSerializer(serializers.ModelSerializer):
    student_name     = serializers.SerializerMethodField()
    reported_by_name = serializers.SerializerMethodField()

    class Meta:
        model = CheatingReport
        fields = [
            "id", "exam",
            "student", "student_name",
            "reported_by", "reported_by_name",
            "severity", "status", "created_at",
        ]

    def get_student_name(self, obj):
        return obj.student.get_full_name() or obj.student.username

    def get_reported_by_name(self, obj):
        return obj.reported_by.get_full_name() or obj.reported_by.username


class CheatingReportSerializer(serializers.ModelSerializer):
    student_name     = serializers.SerializerMethodField()
    reported_by_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    evidence         = CheatingEvidenceSerializer(many=True, read_only=True)

    class Meta:
        model = CheatingReport
        fields = [
            "id", "exam",
            "student", "student_name",
            "reported_by", "reported_by_name",
            "incident_description", "severity", "incident_time",
            "status", "admin_notes",
            "reviewed_by", "reviewed_by_name", "reviewed_at",
            "evidence", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "reported_by", "reported_by_name",
            "reviewed_by", "reviewed_by_name", "reviewed_at",
            "created_at", "updated_at",
        ]

    def get_student_name(self, obj):
        return obj.student.get_full_name() or obj.student.username

    def get_reported_by_name(self, obj):
        return obj.reported_by.get_full_name() or obj.reported_by.username

    def get_reviewed_by_name(self, obj):
        if obj.reviewed_by:
            return obj.reviewed_by.get_full_name() or obj.reviewed_by.username
        return None


class CheatingReportCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CheatingReport
        fields = ["exam", "student", "incident_description", "severity", "incident_time"]

    def validate(self, data):
        if data["student"] == self.context["request"].user:
            raise serializers.ValidationError(
                {"student": "You cannot file a cheating report against yourself."}
            )
        return data

    def create(self, validated_data):
        validated_data["reported_by"] = self.context["request"].user
        return super().create(validated_data)


class CheatingReportAdminUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CheatingReport
        fields = ["status", "admin_notes"]

    def update(self, instance, validated_data):
        instance.status      = validated_data.get("status", instance.status)
        instance.admin_notes = validated_data.get("admin_notes", instance.admin_notes)
        instance.reviewed_by = self.context["request"].user
        instance.reviewed_at = timezone.now()
        instance.save()
        return instance