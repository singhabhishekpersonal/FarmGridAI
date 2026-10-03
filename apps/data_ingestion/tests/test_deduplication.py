"""Deduplication tests: content hashing, DB duplicate checks, perceptual hash."""
import io

import pytest
from PIL import Image

from apps.data_ingestion.services.deduplication import (
    content_digest,
    dhash,
    hamming_distance,
    is_duplicate,
    near_duplicates,
)


class TestHashing:
    def test_content_digest_stable(self):
        assert content_digest(b"hello") == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        assert content_digest("hello") == content_digest(b"hello")


class TestDBDedup:
    def test_same_bytes_is_duplicate(self, db):
        from apps.data_ingestion.models import CollectedArtifact, DataSource

        payload = b"the same bytes"
        first, digest = is_duplicate(payload, model="artifact")
        assert first is False and len(digest) == 64
        source = DataSource.objects.create(name="S1", base_url="https://s1.example.in", source_type="public_dataset")
        CollectedArtifact.objects.create(
            source=source,
            artifact_type="text",
            original_url="https://x.example/data",
            local_path="/tmp/x",
            sha256=digest,
            file_size=len(payload),
        )
        second, _ = is_duplicate(payload, model="artifact")
        assert second is True


class TestPerceptualHash:
    def test_dhash_is_deterministic(self):
        img = Image.new("RGB", (64, 64), "red")
        assert dhash(img) == dhash(Image.new("RGB", (64, 64), "red"))

    def test_near_similar_images_close(self):
        base = Image.new("RGB", (64, 64), (100, 100, 100))
        shade = Image.new("RGB", (64, 64), (104, 100, 100))
        assert hamming_distance(dhash(base), dhash(shade)) < 6

    def test_near_duplicates_filters_by_threshold(self):
        a = 0b1111000011110000
        b = 0b1111000011110001  # hamming distance 1
        c = 0b0000000000000000  # distance 8
        result = near_duplicates(a, [b, c], threshold=4)
        assert len(result) == 1
        assert result[0][0] == b


class TestImageDuplicates:
    def test_identical_image_bytes_dup(self, db):
        from apps.data_ingestion.models import CollectedArtifact, DataSource

        buf = io.BytesIO()
        Image.new("RGB", (32, 32), "blue").save(buf, format="PNG")
        data = buf.getvalue()
        first, digest = is_duplicate(data, model="artifact")
        assert first is False
        source = DataSource.objects.create(name="S2", base_url="https://s2.example.in", source_type="public_dataset")
        CollectedArtifact.objects.create(
            source=source,
            artifact_type="image",
            original_url="https://x.example/a.png",
            local_path="/tmp/a.png",
            sha256=digest,
            file_size=len(data),
        )
        second, _ = is_duplicate(data, model="artifact")
        assert second is True
        assert digest == content_digest(data)