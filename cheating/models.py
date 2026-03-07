from django.db import models
from cloudinary_storage.storage import MediaCloudinaryStorage
from django.conf import settings


def evidence_upload_path(instance, filename):
    return f"cheating_evidence/{instance.report.exam_id}/{instance.report_id}/{filename}"


class CheatingReport(models.Model):

    class Status(models.TextChoices):
        PENDING      = "pending",      "Pending"
        UNDER_REVIEW = "under_review", "Under Review"
        CONFIRMED    = "confirmed",    "Confirmed"
        DISMISSED    = "dismissed",    "Dismissed"

    class SeverityLevel(models.TextChoices):
        LOW    = "low",    "Low"
        MEDIUM = "medium", "Medium"
        HIGH   = "high",   "High"

    exam = models.ForeignKey(
        "exams.Exam",
        on_delete=models.CASCADE,
        related_name="cheating_reports",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="cheating_reports_as_student",
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="cheating_reports_filed",
    )
    incident_description = models.TextField()
    severity = models.CharField(max_length=10, choices=SeverityLevel.choices, default=SeverityLevel.MEDIUM)
    incident_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    admin_notes = models.TextField(blank=True, default="")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="cheating_reports_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("exam", "student", "reported_by")

    def __str__(self):
        return f"Report #{self.pk} | {self.student.get_full_name()} | {self.status}"


class CheatingEvidence(models.Model):

    class EvidenceType(models.TextChoices):
        NOTE     = "note",     "Written Note"
        DOCUMENT = "document", "Document"
        IMAGE    = "image",    "Image"
        OTHER    = "other",    "Other"

    report = models.ForeignKey(
        CheatingReport, on_delete=models.CASCADE, related_name="evidence"
    )
    evidence_type = models.CharField(max_length=20, choices=EvidenceType.choices, default=EvidenceType.NOTE)
    description = models.TextField(blank=True, default="")
    file = models.FileField(
        upload_to=evidence_upload_path,
        storage=MediaCloudinaryStorage(),
        null=True,
        blank=True,
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="uploaded_evidence"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Evidence #{self.pk} for Report #{self.report_id}"

    @property
    def file_url(self):
        return self.file.url if self.file else None