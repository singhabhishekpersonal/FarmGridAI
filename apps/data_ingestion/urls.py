"""URL configuration for the data-ingestion API module."""
from django.urls import path

from apps.data_ingestion.views import (
    ArtifactDetailView,
    ArtifactListView,
    DatasetReportView,
    ManualImportView,
    ProvenanceReportView,
    RecordDetailView,
    RecordListView,
    ReviewQueueApproveView,
    ReviewQueueListView,
    ReviewQueuePublishView,
    ReviewQueueRejectView,
    RunDetailView,
    RunListView,
    SourceCollectView,
    SourceComplianceView,
    SourceDetailView,
    SourceListCreateView,
    SourceRunsView,
)

urlpatterns = [
    # sources
    path("sources", SourceListCreateView.as_view(), name="data-ingestion-sources"),
    path("sources/<uuid:source_id>", SourceDetailView.as_view(), name="data-ingestion-source-detail"),
    path("sources/<uuid:source_id>/compliance-check", SourceComplianceView.as_view(), name="data-ingestion-compliance"),
    path("sources/<uuid:source_id>/collect", SourceCollectView.as_view(), name="data-ingestion-collect"),
    path("sources/<uuid:source_id>/runs", SourceRunsView.as_view(), name="data-ingestion-source-runs"),
    # runs
    path("runs", RunListView.as_view(), name="data-ingestion-runs"),
    path("runs/<uuid:run_id>", RunDetailView.as_view(), name="data-ingestion-run-detail"),
    # artifacts
    path("artifacts", ArtifactListView.as_view(), name="data-ingestion-artifacts"),
    path("artifacts/<uuid:artifact_id>", ArtifactDetailView.as_view(), name="data-ingestion-artifact-detail"),
    # records
    path("records", RecordListView.as_view(), name="data-ingestion-records"),
    path("records/<uuid:record_id>", RecordDetailView.as_view(), name="data-ingestion-record-detail"),
    # review queue
    path("review-queue", ReviewQueueListView.as_view(), name="data-ingestion-review-queue"),
    path(
        "review-queue/<uuid:queue_id>/approve",
        ReviewQueueApproveView.as_view(),
        name="data-ingestion-review-approve",
    ),
    path(
        "review-queue/<uuid:queue_id>/reject",
        ReviewQueueRejectView.as_view(),
        name="data-ingestion-review-reject",
    ),
    path(
        "review-queue/<uuid:queue_id>/publish",
        ReviewQueuePublishView.as_view(),
        name="data-ingestion-review-publish",
    ),
    # manual import + reports
    path("manual-import", ManualImportView.as_view(), name="data-ingestion-manual-import"),
    path("dataset-report", DatasetReportView.as_view(), name="data-ingestion-dataset-report"),
    path("provenance-report", ProvenanceReportView.as_view(), name="data-ingestion-provenance-report"),
]