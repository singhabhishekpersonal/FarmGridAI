"""Abstract base models providing audit, soft-delete and timestamp fields."""
import uuid

from django.conf import settings
from django.db import models

from apps.core.constants import ConfidenceLevel


class SoftDeleteQuerySet(models.QuerySet):
    """QuerySet that excludes soft-deleted rows by default."""

    def delete(self):
        for obj in self.only("pk"):
            obj.delete()
        return super().delete()

    def hard_delete(self):
        return super().delete()


class SoftDeleteManager(models.Manager):
    """Default manager that only returns active (non-soft-deleted) rows."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)

    def all_with_deleted(self):
        return super().get_queryset()


class AllObjectsManager(models.Manager):
    """Manager that returns every row including soft-deleted ones."""

    def get_queryset(self):
        return super().get_queryset()


class TimeStampedModel(models.Model):
    """Abstract base model with UUID PK and created/updated timestamps.

    The UUID primary key keeps internal identifiers opaque in API responses.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AuditModel(models.Model):
    """Abstract mixin recording who created/updated a record.

    ``created_by``/``updated_by`` may be null for system-generated records
    (e.g. seeds or Celery tasks).
    """

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        editable=False,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        editable=False,
    )

    class Meta:
        abstract = True


class SoftDeleteModel(models.Model):
    """Abstract mixin implementing soft deletes.

    Deleted records are hidden from default queries but retained for audit.
    """

    is_active = models.BooleanField(default=True, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        from django.utils import timezone

        self.deleted_at = timezone.now()
        self.is_active = False
        self.save(update_fields=["deleted_at", "is_active", "updated_at"])
        return 1, {}

    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)


class BaseModel(TimeStampedModel, AuditModel, SoftDeleteModel):
    """Aggregated abstract base model used by most domain models.

    Provides:
    - UUID primary key
    - created_at / updated_at
    - created_by / updated_by audit trail
    - is_active + soft delete support
    """

    class Meta:
        abstract = True


class ConfidenceMixin(models.Model):
    """Shared confidence/uncertainty fields for any estimate model."""

    confidence = models.CharField(
        max_length=10,
        choices=ConfidenceLevel.choices,
        default=ConfidenceLevel.LOW,
    )
    needs_confirmation = models.BooleanField(default=True)
    assumptions_json = models.JSONField(default=list, blank=True)
    limitations_json = models.JSONField(default=list, blank=True)

    class Meta:
        abstract = True