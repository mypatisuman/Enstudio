"""Lenient Mongo document models for stable collections (Phase 2).

These validate-on-read at the repository boundary. AliasChoices absorb the
historical field-name variance (`vendor`/`vendor_name`, `strategy`/`stratergy`)
so call sites stop doing `doc.get('vendor', doc.get('vendor_name'))`.
"""

from datetime import datetime
from typing import Any

from pydantic import AliasChoices, Field

from common.models.base import LenientModel, MongoModel


class NotificationDoc(MongoModel):
    """Admin notification (collection: notifications)."""
    user_id: int | None = None
    username: str = "Unknown"
    user_email: str = ""
    failed_step: str = "Unknown"
    error_message: str = ""
    title: str | None = None
    message: str | None = None
    status: str = "failed"
    type: str = "failure"
    task_type: str | None = None
    play_sound: bool = False
    stream_id: str | None = None
    target_url: str | None = None
    page: str = "unknown"
    is_read: bool = False
    created_at: datetime | None = None
    additional_context: dict[str, Any] = Field(default_factory=dict)

    def to_api_dict(self) -> dict[str, Any]:
        """Frontend-facing shape (matches the legacy hand-built dict exactly)."""
        created = self.created_at
        return {
            "id": str(self.id) if self.id else None,
            "user_id": self.user_id,
            "username": self.username,
            "user_email": self.user_email,
            "failed_step": self.failed_step,
            "error_message": self.error_message,
            "title": self.title or self.failed_step,
            "message": self.message or self.error_message,
            "status": self.status,
            "type": self.type,
            "task_type": self.task_type,
            "play_sound": self.play_sound,
            "stream_id": self.stream_id,
            "target_url": self.target_url,
            "page": self.page,
            "is_read": self.is_read,
            "created_at": created.isoformat() if isinstance(created, datetime) else (created or ""),
            "additional_context": self.additional_context,
        }


class VendorDoc(MongoModel):
    """Vendor catalog entry (collection: vendors). Demonstrates vendor/vendor_name AliasChoices."""
    model_config = {"protected_namespaces": ()}

    vendor: str = Field(default="", validation_alias=AliasChoices("vendor", "vendor_name"))
    product_type: str = ""
    model_families: list[str] = Field(default_factory=list)
    description: str = ""



