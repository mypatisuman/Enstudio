"""Shared Pydantic foundations: ObjectId type, base models, and Mongo mapping helpers."""

from datetime import datetime  # noqa: F401  (re-exported for model authors)
from typing import Annotated, Any

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import core_schema


class _ObjectIdAnnotation:
    """Lets Pydantic v2 accept/serialize bson.ObjectId (str on the wire, ObjectId in Python)."""

    @classmethod
    def __get_pydantic_core_schema__(cls, _source, _handler):
        def _validate(v: Any) -> ObjectId:
            if isinstance(v, ObjectId):
                return v
            if isinstance(v, str) and ObjectId.is_valid(v):
                return ObjectId(v)
            raise ValueError(f"Invalid ObjectId: {v!r}")

        return core_schema.json_or_python_schema(
            json_schema=core_schema.no_info_plain_validator_function(_validate),
            python_schema=core_schema.no_info_plain_validator_function(_validate),
            serialization=core_schema.plain_serializer_function_ser_schema(str, when_used="json"),
        )

    @classmethod
    def __get_pydantic_json_schema__(cls, _schema, handler):
        return handler(core_schema.str_schema())


PyObjectId = Annotated[ObjectId, _ObjectIdAnnotation]


class AppModel(BaseModel):
    """Strict base for trusted/boundary models (HTTP request bodies, internal contracts)."""
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)


class LenientModel(BaseModel):
    """Tolerant base for internal/reference data — keeps unknown fields, tolerates missing ones."""
    model_config = ConfigDict(extra="allow", populate_by_name=True, str_strip_whitespace=True)


class MongoModel(LenientModel):
    """Lenient model with Mongo `_id` handling and JSON-safe dumps. Validate-on-read at repositories."""
    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        str_strip_whitespace=True,
        arbitrary_types_allowed=True,
    )

    id: PyObjectId | None = Field(default=None, alias="_id")

    @classmethod
    def from_mongo(cls, doc: dict[str, Any] | None):
        """Build a model from a raw pymongo document (or None)."""
        if doc is None:
            return None
        return cls.model_validate(doc)

    def to_mongo(self) -> dict[str, Any]:
        """Serialize for insert/update. Drops `_id` when unset so Mongo generates one."""
        data = self.model_dump(by_alias=True, exclude_none=False)
        if data.get("_id") is None:
            data.pop("_id", None)
        return data

    def to_json_dict(self) -> dict[str, Any]:
        """JSON-safe dict (ObjectId -> str, datetime -> isoformat), nulls dropped."""
        return self.model_dump(by_alias=True, mode="json", exclude_none=True)
