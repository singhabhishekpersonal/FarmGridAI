"""Content-hashing helpers used for deduplication and provenance."""
import hashlib


def sha256_of_bytes(data):
    """Hex SHA-256 of a bytes payload."""
    return hashlib.sha256(data).hexdigest()


def sha256_of_file(path):
    """Hex SHA-256 of a file on disk (streamed)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def short_hash(value, length=16):
    """Stable short digest (hex) of a string/bytes value for IDs."""
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()[:length]