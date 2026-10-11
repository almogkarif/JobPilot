"""Lossless, versioned storage for personalized ranking JSON in existing TEXT.

The public dictionary is immutable for version 1. It contains ranking code
literals and an empty schema, never candidate or job data. The nine SQL diagnostic
gates remain readable without decoding; ORM callers receive the original string.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path
import zlib

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

MAX_RANKING_STORAGE_BYTES = 256 * 1024
MIN_RANKING_STORAGE_BYTES = 1024
MIN_STORAGE_SAVING_BYTES = 128
STORAGE_MARKER = "_jp_rank"
STORAGE_VERSION = 1
DICTIONARY_SHA256 = "60197a89f3e65d3f796e9897620474c5062c129881087079d6906c4a45b454da"
DICTIONARY = Path(__file__).with_name("ranking_storage_dictionary_v1.txt").read_bytes()
if hashlib.sha256(DICTIONARY).hexdigest() != DICTIONARY_SHA256:
    raise RuntimeError("Ranking storage dictionary version 1 checksum mismatch")

SQL_ELIGIBILITY_FIELDS = (
    "career_track_status", "seniority_status", "explicit_exclusion",
    "experience_status", "degree_status", "recency_status", "location_status",
    "work_mode_status", "employment_type_status",
)
_ENVELOPE_FIELDS = {STORAGE_MARKER, "n", "eligibility", "data"}
_ENVELOPE_PREFIX = '{"_jp_rank":'


class RankingStorageError(ValueError):
    """The stored ranking envelope cannot be safely and exactly decoded."""


def _json(value):
    # Nonstandard constants cannot be queried as PostgreSQL JSONB.
    def invalid_constant(_value):
        raise ValueError("Nonstandard JSON constant")
    return json.loads(value, parse_constant=invalid_constant)


def _eligibility_projection(payload):
    eligibility = payload["eligibility"]
    return {key: eligibility[key] for key in SQL_ELIGIBILITY_FIELDS if key in eligibility}


def _ranking_payload(payload):
    return (isinstance(payload, dict) and payload.get("engine") == "v2"
            and isinstance(payload.get("eligibility"), dict)
            and isinstance(payload.get("breakdown"), dict))


def encode_ranking_result(value: str | None) -> str | None:
    """Encode only bounded ranking JSON that yields a material byte saving."""
    if not isinstance(value, str):
        return value
    try:
        original = value.encode("utf-8")
    except UnicodeEncodeError:
        return value
    if not MIN_RANKING_STORAGE_BYTES <= len(original) <= MAX_RANKING_STORAGE_BYTES:
        return value
    try:
        payload = _json(value)
    except (ValueError, RecursionError):
        return value
    # Existing reserved-name collisions remain plain and are never nested.
    if not _ranking_payload(payload) or STORAGE_MARKER in payload:
        return value
    compressor = zlib.compressobj(9, zdict=DICTIONARY)
    compressed = compressor.compress(original) + compressor.flush()
    envelope = json.dumps({
        STORAGE_MARKER: STORAGE_VERSION, "n": len(original),
        "eligibility": _eligibility_projection(payload),
        "data": base64.b64encode(compressed).decode("ascii"),
    }, ensure_ascii=False, separators=(",", ":"))
    encoded_bytes = len(envelope.encode("utf-8"))
    return envelope if (encoded_bytes <= MAX_RANKING_STORAGE_BYTES
                        and encoded_bytes + MIN_STORAGE_SAVING_BYTES <= len(original)) else value


def decode_ranking_result(value: str | None) -> str | None:
    """Read legacy JSON unchanged; fail clearly for recognized corrupt envelopes."""
    if not isinstance(value, str) or STORAGE_MARKER not in value:
        return value
    try:
        encoded_bytes = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        return value
    # Normally skip oversized legacy JSON. Marker-leading values must first be
    # classified because an actual ranking can also contain the reserved name.
    oversized = encoded_bytes > MAX_RANKING_STORAGE_BYTES
    if oversized and not value.lstrip().startswith(_ENVELOPE_PREFIX):
        return value
    try:
        envelope = _json(value)
    except (ValueError, RecursionError) as exc:
        if value.lstrip().startswith(_ENVELOPE_PREFIX):
            raise RankingStorageError("Invalid ranking storage envelope JSON") from exc
        return value
    if not isinstance(envelope, dict) or STORAGE_MARKER not in envelope:
        return value
    # A legacy ranking remains a ranking even if it happens to use the reserved
    # name. A marker by itself also does not constitute the storage envelope.
    if _ranking_payload(envelope) or not ({"n", "data"} & envelope.keys()):
        return value
    if oversized:
        raise RankingStorageError("Ranking storage envelope exceeds 256 KiB")
    if type(envelope[STORAGE_MARKER]) is not int and set(envelope) != _ENVELOPE_FIELDS:
        return value
    if (set(envelope) != _ENVELOPE_FIELDS
            or type(envelope[STORAGE_MARKER]) is not int
            or envelope[STORAGE_MARKER] != STORAGE_VERSION):
        raise RankingStorageError("Unsupported or invalid ranking storage envelope")
    size, data = envelope["n"], envelope["data"]
    if (type(size) is not int or not 1 <= size <= MAX_RANKING_STORAGE_BYTES
            or not isinstance(data, str) or not isinstance(envelope["eligibility"], dict)):
        raise RankingStorageError("Invalid ranking storage payload bounds")
    try:
        compressed = base64.b64decode(data, validate=True)
        decompressor = zlib.decompressobj(zdict=DICTIONARY)
        original = decompressor.decompress(compressed, size + 1)
        if (len(original) != size or not decompressor.eof
                or decompressor.unused_data or decompressor.unconsumed_tail):
            raise RankingStorageError("Truncated, trailing or oversized ranking storage payload")
        decoded = original.decode("utf-8")
        payload = _json(decoded)
    except (binascii.Error, zlib.error, UnicodeError, ValueError, RecursionError) as exc:
        raise RankingStorageError("Invalid compressed ranking storage payload") from exc
    if not _ranking_payload(payload) or _eligibility_projection(payload) != envelope["eligibility"]:
        raise RankingStorageError("Ranking storage eligibility projection mismatch")
    return decoded


class RankingResultText(TypeDecorator):
    """Existing TEXT schema, with exact-string transparency at the ORM boundary."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encode_ranking_result(value)

    def process_result_value(self, value, dialect):
        return decode_ranking_result(value)
