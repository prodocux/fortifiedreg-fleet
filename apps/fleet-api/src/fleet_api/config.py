"""
Central configuration module for FortifiedReg Fleet API (v0.3.0).
Enforces fail-closed environment validation, adapter mode allowlists, and secrets management.
"""
import os
from typing import Set

ALLOWED_ENVS: Set[str] = {"production", "staging", "test", "local", "dev"}
ALLOWED_ADAPTER_MODES: Set[str] = {"live", "fake"}


def get_fleet_env() -> str:
    raw = os.getenv("FLEET_ENV", "production")
    if not raw or not raw.strip():
        raise ValueError("FLEET_ENV cannot be empty.")
    val = raw.strip().lower()
    if val not in ALLOWED_ENVS:
        raise ValueError(f"Invalid FLEET_ENV: '{val}'. Must be one of {sorted(ALLOWED_ENVS)}.")
    return val


def get_adapter_mode(env_var_name: str, fleet_env: str) -> str:
    default_mode = "fake" if fleet_env in ("test", "local", "dev") else "live"
    val = os.getenv(env_var_name, default_mode).strip().lower()
    if val not in ALLOWED_ADAPTER_MODES:
        raise ValueError(f"Invalid {env_var_name}: '{val}'. Must be 'live' or 'fake'.")
    if fleet_env in ("production", "staging") and val == "fake":
        if "INTAKE" in env_var_name:
            raise RuntimeError(
                "Fail-closed: Fake intake adapter is prohibited in production/staging environment. "
                "Set FLEET_INTAKE_ADAPTER=live or use FLEET_ENV=test/local/dev."
            )
        elif "PDX" in env_var_name:
            raise RuntimeError(
                "Fail-closed: Fake PDX orchestrator is prohibited in production/staging environment. "
                "Set FLEET_PDX_ADAPTER=live or use FLEET_ENV=test/local/dev."
            )
    return val


FLEET_ENV = get_fleet_env()
INTAKE_MODE = get_adapter_mode("FLEET_INTAKE_ADAPTER", FLEET_ENV)
PDX_MODE = get_adapter_mode("FLEET_PDX_ADAPTER", FLEET_ENV)

FLEET_DB_PATH = os.getenv("FLEET_DB_PATH", ":memory:")
FLEET_ARTIFACTS_DIR = os.getenv("FLEET_ARTIFACTS_DIR", "./.local_artifacts")

_env_secret = os.getenv("FLEET_JWT_SECRET")
if not _env_secret:
    if FLEET_ENV in ("test", "local", "dev"):
        FLEET_JWT_SECRET = "dev-secret-key-fortified-enterprise-fleet-2026-secure-token-512"
    else:
        raise RuntimeError(
            "CRITICAL SECURITY: FLEET_JWT_SECRET environment variable is mandatory and cannot be empty in production/staging environments."
        )
else:
    FLEET_JWT_SECRET = _env_secret

FLEET_JWT_ALGORITHM = "HS256"
FLEET_JWT_ISSUER = "fortified-enterprise-fleet-auth"
