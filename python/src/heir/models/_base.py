"""The base of every generated model."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, SerializerFunctionWrapHandler, field_serializer


class HeirModel(BaseModel):
    """A generated model. Fields are snake_case here and camelCase on the wire; both spellings construct a model.

    Unknown fields in an answer are ignored, as the API asks: fields are only ever added. A datetime is sent at
    millisecond precision and in UTC, which is the most the API accepts.
    """

    model_config = ConfigDict(populate_by_name=True)

    @field_serializer("*", mode="wrap", when_used="json", check_fields=False)
    def _serialize_json(self, value: Any, handler: SerializerFunctionWrapHandler) -> Any:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        return handler(value)
