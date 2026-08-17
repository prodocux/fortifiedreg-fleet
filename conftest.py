"""
Pytest Root Configuration & Environment Initialization.
Sets default testing environment variables unless explicitly overridden.
"""
import os

os.environ.setdefault("FLEET_ENV", "test")
os.environ.setdefault("FLEET_JWT_SECRET", "dev-secret-key-fortified-enterprise-fleet-2026-secure-token-512")
