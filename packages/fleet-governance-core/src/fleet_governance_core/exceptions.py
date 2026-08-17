"""
Domain Exceptions for Fleet Governance Core.
"""

class GovernanceException(Exception):
    """Base exception for all governance domain errors."""
    pass

class PreconditionFailedError(GovernanceException):
    """Raised when case, plan, or evidence digests mismatch during approval (HTTP 412)."""
    pass

class IdempotencyConflictError(GovernanceException):
    """Raised when an idempotency key is reused with differing request content (HTTP 409)."""
    pass

class CheckpointNotFoundError(GovernanceException):
    """Raised when a specified checkpoint is not found (HTTP 404)."""
    pass

class CheckpointNotPendingError(GovernanceException):
    """Raised when attempting to decide a checkpoint that is not in pending state (HTTP 409)."""
    pass

class SecurityScanBlockedError(GovernanceException):
    """Raised when security scanners detect prompt injection or policy violation (HTTP 400)."""
    pass
