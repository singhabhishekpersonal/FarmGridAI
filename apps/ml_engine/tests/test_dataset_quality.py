"""Sanity checks for the prepared top-6 tractor-brand dataset.

These tests guard the *prepared artifact* so future rebuilds cannot silently
ship an empty class folder, a leakage across splits, or a class disappearing.
The dataset lives outside the Django tree; the path is resolved from settings
(ML_EQUIPMENT_CLASSIFIER_ARTIFACT_DIR's parent) and is optional in CI.
"""
import json
from pathlib import Path

import pytest
from django.conf import settings

DATASET_DIR = Path(settings.BASE_DIR).parent / "open-tractor" / "data" / "tractor_brand_dataset"
EXPECTED_BRANDS = {"Farmtrac", "John Deere", "Mahindra", "New Holland", "Powertrac", "Sonalika"}
EXPECTED_SPLITS = ["train", "val", "test"]


def _dataset_exists():
    return (DATASET_DIR / "labels.json").is_file()


@pytest.fixture(scope="module")
def dataset():
    if not _dataset_exists():
        pytest.skip("prepared dataset not present")
    return DATASET_DIR


def _index_dir(dataset, split):
    idx = {}
    for path in sorted((dataset / split).rglob("*.webp")) + sorted((dataset / split).rglob("*.jpg")) + sorted((dataset / split).rglob("*.jpeg")) + sorted((dataset / split).rglob("*.png")):
        idx[path.name] = str(path)
    return idx


def test_labels_json_present_and_has_expected_classes(dataset):
    labels = json.loads((dataset / "labels.json").read_text(encoding="utf-8"))
    assert set(labels["classes"]) == EXPECTED_BRANDS | {"other", "unknown"}
    assert set(labels["top_brands"]) == EXPECTED_BRANDS
    assert labels["unknown_label"] == "unknown"


def test_no_empty_class_folder(dataset):
    for split in EXPECTED_SPLITS:
        class_dirs = [p for p in (dataset / split).iterdir() if p.is_dir()]
        assert class_dirs, f"{split} has no class folders"
        for cd in class_dirs:
            count = sum(1 for _ in cd.iterdir())
            assert count > 0, f"empty class folder {split}/{cd.name}"


def test_no_split_leakage(dataset):
    """No two files with the same name appear in more than one split."""
    seen = {}
    for split in EXPECTED_SPLITS:
        idx = _index_dir(dataset, split)
        for name in idx:
            if name in seen:
                pytest.fail(f"file {name} present in {seen[name]} and {split}")
            seen[name] = split


def test_unknown_has_no_images(dataset):
    for split in EXPECTED_SPLITS:
        folder = dataset / split / "unknown"
        assert folder.exists() is False, f"{split}/unknown must not exist"