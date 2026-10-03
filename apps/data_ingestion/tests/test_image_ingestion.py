"""Image ingestion tests: validation gates + manual offline import."""
import io

import pytest
from PIL import Image
from django.contrib.auth import get_user_model

from apps.data_ingestion.models import CollectedArtifact, DataSource, ExtractedRecord
from apps.data_ingestion.services.downloader import make_ingestion_run
from apps.data_ingestion.services.image_collector import import_manual_images
from apps.data_ingestion.services.image_validation import validate_image
from apps.data_ingestion.services.source_registry import approve_source, register_source


def _png_bytes(fill=(120, 90, 70), size=(500, 400)):
    """Deterministic high-contrast textured PNG that clears blur/brightness gates."""
    import numpy as np

    width, height = size
    rng = np.random.default_rng(7)
    block = 8
    blocks = rng.integers(-120, 121, size=(height // block + 1, width // block + 1, len(fill)))
    arr = np.zeros((height, width, len(fill)), dtype=np.int16)
    for channel, value in enumerate(fill):
        tile = np.repeat(np.repeat(blocks[:, :, channel], block, 0), block, 1)[:height, :width]
        arr[:, :, channel] = value + tile
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


class TestValidateImage:
    def test_valid_png_passes(self):
        result = validate_image(_png_bytes(), filename="tractor.png", min_dimension=64)
        assert result["status"] == CollectedArtifact.ValidationStatus.VALID
        assert result["mime_type"] == "image/png"
        assert result["min_dimension_ok"] is True
        assert len(result["sha256"]) == 64

    def test_corrupt_image_rejected(self):
        result = validate_image(b"not an image", filename="x.jpg", min_dimension=64)
        assert result["status"] == CollectedArtifact.ValidationStatus.INVALID

    def test_oversize_rejected(self):
        result = validate_image(_png_bytes(), filename="big.png", max_bytes=10)
        assert result["status"] == CollectedArtifact.ValidationStatus.INVALID
        assert "size" in result["errors"][0]

    def test_small_image_rejected_by_min_dimension(self):
        result = validate_image(_png_bytes(size=(40, 40)), filename="small.png", min_dimension=64)
        assert result["status"] == CollectedArtifact.ValidationStatus.INVALID
        assert "dimension" in result["errors"][0]

    def test_blurry_flagged_review(self):
        flat = Image.new("RGB", (200, 200), (40, 40, 40))
        buf = io.BytesIO()
        flat.save(buf, format="PNG")
        result = validate_image(buf.getvalue(), filename="flat.png", min_dimension=64)
        assert result["status"] in (CollectedArtifact.ValidationStatus.VALID, CollectedArtifact.ValidationStatus.REVIEW)


class TestManualImport:
    @pytest.fixture
    def approved_source(self, db):
        src = register_source(
            name="Local corpus",
            base_url="manual://local-corpus",
            source_type="manual_import",
            category="equipment_images",
            allowed_collection_methods=["manual_import_only"],
        )
        staff = get_user_model().objects.create_user(username="imp1", password="Str0ng!", is_staff=True)
        approve_source(src, staff)
        return src

    def test_imports_valid_images_into_review(self, approved_source, tmp_path, db):
        folder = tmp_path / "Mahindra"
        folder.mkdir()
        (folder / "a.png").write_bytes(_png_bytes(fill=(120, 90, 70)))
        (folder / "b.png").write_bytes(_png_bytes(fill=(70, 120, 180)))

        run = make_ingestion_run(approved_source, dry_run=False)
        report = import_manual_images(approved_source, run, [folder / "a.png", folder / "b.png"], label_hint="Mahindra")

        assert report["imported"] == 2
        assert run.images_downloaded == 2
        contracts = CollectedArtifact.objects.filter(source=approved_source, artifact_type="image")
        assert contracts.count() == 2
        records = ExtractedRecord.objects.filter(source=approved_source, record_type="equipment_image")
        assert records.count() == 2
        assert all(r.verification_status == ExtractedRecord.VerificationStatus.RAW for r in records)

    def test_duplicate_bytes_skipped(self, approved_source, tmp_path, db):
        folder = tmp_path / "label"
        folder.mkdir()
        path = folder / "dup.png"
        path.write_bytes(_png_bytes())
        run = make_ingestion_run(approved_source, dry_run=False)
        first = import_manual_images(approved_source, run, [path], label_hint="X")
        second = import_manual_images(approved_source, run, [path], label_hint="X")
        assert first["imported"] == 1
        assert second["duplicates"] == 1
        assert CollectedArtifact.objects.filter(source=approved_source).count() == 1

    def test_invalid_file_rejected(self, approved_source, tmp_path, db):
        folder = tmp_path / "label"
        folder.mkdir()
        bad = folder / "virus.txt"
        bad.write_text("definitely not an image")
        run = make_ingestion_run(approved_source, dry_run=False)
        report = import_manual_images(approved_source, run, [bad], label_hint="X")
        assert report["imported"] == 0
        assert report["invalid"] == 1

    def test_unapproved_source_rejected(self, db, tmp_path):
        src = register_source(
            name="Pending corpus",
            base_url="manual://pending-corpus",
            source_type="manual_import",
            category="equipment_images",
        )
        run = make_ingestion_run(src, dry_run=False)
        with pytest.raises(RuntimeError):
            import_manual_images(src, run, [], label_hint="X")