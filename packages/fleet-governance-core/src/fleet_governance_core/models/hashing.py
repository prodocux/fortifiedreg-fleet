"""
Canonical hashing utilities for Fortified Enterprise Fleet.
Follows G1 frozen specification:
UTF-8 encoded, sorted keys, no whitespace, ensure_ascii=False.
"""
import hashlib
import json
from typing import Any
from pydantic import BaseModel

def canonical_json_dumps(data: Any) -> str:
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json")
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':'))

def compute_data_sha256(data: Any) -> str:
    raw_bytes = canonical_json_dumps(data).encode("utf-8")
    return hashlib.sha256(raw_bytes).hexdigest()
