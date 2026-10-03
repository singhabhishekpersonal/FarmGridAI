"""Deduplication by content hash and perceptual (dHash) similarity."""
from apps.data_ingestion.models import CollectedArtifact, ExtractedRecord
from apps.data_ingestion.services.hashing import sha256_of_bytes


def content_digest(data):
    """Hex SHA-256 of arbitrary bytes/str."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return sha256_of_bytes(data)


def artifact_duplicate(sha256):
    return CollectedArtifact.objects.filter(sha256=sha256).exists()


def record_duplicate(content_hash):
    return ExtractedRecord.objects.filter(content_hash=content_hash).exists()


def is_duplicate(data, *, model="artifact"):
    digest = content_digest(data)
    if model == "artifact":
        return artifact_duplicate(digest), digest
    return record_duplicate(digest), digest


def dhash(img, hash_size=8):
    """Difference-hash 64-bit integer for a PIL image (grayscale)."""
    from PIL import Image

    if img.mode != "L":
        img = img.convert("L")
    img = img.resize((hash_size + 1, hash_size), Image.LANCZOS)
    pixels = list(img.tobytes())
    differences = []
    for row in range(hash_size):
        for col in range(hash_size):
            left = pixels[row * (hash_size + 1) + col]
            right = pixels[row * (hash_size + 1) + col + 1]
            differences.append(int(left > right))
    bit_string = "".join("1" if b else "0" for b in differences)
    return int(bit_string, 2)


def hamming_distance(a, b):
    return (a ^ b).bit_count()


def near_duplicates(phash, candidates, threshold=6):
    """Return candidate (phash, key) pairs within a Hamming distance."""
    return [(cand, distance) for cand, distance in ((c, hamming_distance(phash, c)) for c in candidates) if distance <= threshold] if candidates else []