from enum import StrEnum


class ProcessingStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSED = "PROCESSED"
    NOT_JOB = "NOT_JOB"
    DUPLICATE = "DUPLICATE"
    PENDING_AI = "PENDING_AI"
    PENDING_VISION = "PENDING_VISION"
    RATE_LIMITED = "RATE_LIMITED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    VISION_FAILED = "VISION_FAILED"
    SKIPPED = "SKIPPED"


class Classification(StrEnum):
    APPLY = "APPLY"
    REVIEW = "REVIEW"
    IGNORE = "IGNORE"


class JobStatus(StrEnum):
    NEW = "NEW"
    NOTIFIED = "NOTIFIED"
    APPLIED = "APPLIED"
    SAVED = "SAVED"
    DISMISSED = "DISMISSED"


class UserAction(StrEnum):
    APPLIED = "APPLIED"
    SAVED = "SAVED"
    SKIPPED = "SKIPPED"
