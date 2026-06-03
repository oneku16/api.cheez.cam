from enum import StrEnum


class UserRole(StrEnum):
    OWNER = "owner"
    SUPERADMIN = "superadmin"


class EventStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ARCHIVED = "archived"


class QrStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class PhotoStatus(StrEnum):
    PROCESSING = "processing"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DELETED = "deleted"
    FAILED = "failed"


class AccessStatus(StrEnum):
    ALLOWED = "allowed"
    NOT_PUBLISHED = "not_published"
    NOT_STARTED = "not_started"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ARCHIVED = "archived"
    UPLOADS_DISABLED = "uploads_disabled"
    NOT_FOUND = "not_found"
