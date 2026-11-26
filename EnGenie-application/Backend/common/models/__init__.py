"""Shared Pydantic model foundations (boundaries strict, internal data lenient)."""

from common.models.base import AppModel, LenientModel, MongoModel, PyObjectId
from common.models.cache import cache_key
from common.models.documents import NotificationDoc, VendorDoc
from common.models.strategy import StrategyEntry
from common.models.serialization import dump_for_redis, load_from_redis
from common.models.taxonomy import ModelFamily, Product, ProductType, Taxonomy, VendorProduct
from common.models.validation import validate_response

__all__ = [
    "AppModel",
    "LenientModel",
    "MongoModel",
    "PyObjectId",
    "cache_key",
    "NotificationDoc",
    "StrategyEntry",
    "VendorDoc",
    "dump_for_redis",
    "load_from_redis",
    "validate_response",
    "Taxonomy",
    "ProductType",
    "Product",
    "ModelFamily",
    "VendorProduct",
]
