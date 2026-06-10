import uuid
from datetime import datetime

from sqlalchemy import Uuid
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


class SoftDeleteMixin(UUIDPrimaryKeyMixin):
    deleted_at: Mapped[datetime | None] = mapped_column("deletedAt", TIMESTAMP(precision=3), nullable=True)
