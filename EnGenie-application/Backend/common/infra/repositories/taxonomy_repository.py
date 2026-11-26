"""Active MongoDB repository for the dynamic 4-level Taxonomy tree.

Supports atomic and idempotent CRUD operations at any node depth using positional
array filters, avoiding the need to write the entire tree on every update.
"""

import logging
from typing import Any

from common.infra.mongodb_config import get_mongodb_connection
from common.models.taxonomy import Taxonomy, ProductType, Product, ModelFamily, VendorProduct

logger = logging.getLogger(__name__)

TAXONOMY_TREE_COLLECTION = "taxonomy_tree"


def _get_collection():
    """Get the taxonomy_tree collection from MongoDB."""
    conn = get_mongodb_connection()
    # Store tree documents in the database
    return conn["database"][TAXONOMY_TREE_COLLECTION]


class TaxonomyRepository:
    """Repository handling active CRUD and specification cascades in MongoDB."""

    @staticmethod
    def get_full_taxonomy() -> Taxonomy:
        """Fetch all ProductType documents and reconstruct the complete multi-root Taxonomy tree."""
        try:
            collection = _get_collection()
            docs = list(collection.find({}))
            return Taxonomy.from_mongo_docs(docs)
        except Exception as e:
            logger.error(f"[TaxonomyRepository] Failed to fetch full taxonomy: {e}")
            return Taxonomy(product_types=[])

    @staticmethod
    def add_product_type(pt: ProductType) -> bool:
        """Idempotently insert a new ProductType document."""
        try:
            collection = _get_collection()
            existing = collection.find_one({"name": pt.name})
            if existing:
                logger.info(f"[TaxonomyRepository] ProductType '{pt.name}' already exists, skipping insert.")
                return True
            collection.insert_one(pt.to_mongo_doc())
            logger.info(f"[TaxonomyRepository] Created new ProductType: '{pt.name}'")
            return True
        except Exception as e:
            logger.error(f"[TaxonomyRepository] Failed to add ProductType '{pt.name}': {e}")
            return False

    @staticmethod
    def add_product(product_type_name: str, p: Product) -> bool:
        """Idempotently and atomically append a Product to a ProductType."""
        try:
            collection = _get_collection()
            # Push only if a product with the same name does not exist
            result = collection.update_one(
                {"name": product_type_name, "products.name": {"$ne": p.name}},
                {"$push": {"products": p.model_dump(exclude_none=False)}}
            )
            success = result.modified_count > 0
            if success:
                logger.info(f"[TaxonomyRepository] Appended Product '{p.name}' to ProductType '{product_type_name}'")
            else:
                logger.info(f"[TaxonomyRepository] Product '{p.name}' already exists in ProductType '{product_type_name}'")
            return True
        except Exception as e:
            logger.error(f"[TaxonomyRepository] Failed to add Product '{p.name}' to '{product_type_name}': {e}")
            return False

    @staticmethod
    def add_model_family(product_type_name: str, product_name: str, mf: ModelFamily) -> bool:
        """Idempotently and atomically append a ModelFamily to a Product using array filters."""
        try:
            collection = _get_collection()
            # Push only if model family name does not exist under that product
            result = collection.update_one(
                {
                    "name": product_type_name,
                    "products.name": product_name,
                    "products.model_families.name": {"$ne": mf.name}
                },
                {"$push": {"products.$[prod].model_families": mf.model_dump(exclude_none=False)}},
                array_filters=[{"prod.name": product_name}]
            )
            success = result.modified_count > 0
            if success:
                logger.info(f"[TaxonomyRepository] Appended ModelFamily '{mf.name}' to Product '{product_name}'")
            else:
                logger.info(f"[TaxonomyRepository] ModelFamily '{mf.name}' already exists in Product '{product_name}'")
            return True
        except Exception as e:
            logger.error(f"[TaxonomyRepository] Failed to add ModelFamily '{mf.name}' to '{product_name}': {e}")
            return False

    @staticmethod
    def add_vendor_product(product_type_name: str, product_name: str, family_name: str, vp: VendorProduct) -> bool:
        """Idempotently and atomically append a VendorProduct to a ModelFamily."""
        try:
            collection = _get_collection()
            # Push only if vendor product name does not exist under that model family
            result = collection.update_one(
                {
                    "name": product_type_name,
                    "products.name": product_name,
                    "products.model_families.name": family_name,
                    "products.model_families.vendor_products.name": {"$ne": vp.name}
                },
                {"$push": {"products.$[prod].model_families.$[fam].vendor_products": vp.model_dump(exclude_none=False)}},
                array_filters=[
                    {"prod.name": product_name},
                    {"fam.name": family_name}
                ]
            )
            success = result.modified_count > 0
            if success:
                logger.info(f"[TaxonomyRepository] Appended VendorProduct '{vp.name}' to Family '{family_name}'")
            else:
                logger.info(f"[TaxonomyRepository] VendorProduct '{vp.name}' already exists in Family '{family_name}'")
            return True
        except Exception as e:
            logger.error(f"[TaxonomyRepository] Failed to add VendorProduct '{vp.name}' to '{family_name}': {e}")
            return False

    @staticmethod
    def delete_node(level: str, name: str) -> bool:
        """Idempotently delete/prune a dynamic taxonomy node from the database by name at any level."""
        try:
            collection = _get_collection()
            lvl = level.strip().lower()
            if lvl in ("product_type", "producttype"):
                result = collection.delete_one({"name": name})
                logger.info(f"[TaxonomyRepository] Deleted ProductType '{name}' (deleted count={result.deleted_count})")
            elif lvl == "product":
                result = collection.update_many({}, {"$pull": {"products": {"name": name}}})
                logger.info(f"[TaxonomyRepository] Pulled Product '{name}' (modified count={result.modified_count})")
            elif lvl in ("model_family", "modelfamily"):
                result = collection.update_many({}, {"$pull": {"products.$[].model_families": {"name": name}}})
                logger.info(f"[TaxonomyRepository] Pulled ModelFamily '{name}' (modified count={result.modified_count})")
            elif lvl in ("vendor_product", "vendorproduct"):
                result = collection.update_many(
                    {},
                    {"$pull": {"products.$[].model_families.$[].vendor_products": {"name": name}}}
                )
                logger.info(f"[TaxonomyRepository] Pulled VendorProduct '{name}' (modified count={result.modified_count})")
            else:
                logger.error(f"[TaxonomyRepository] Invalid pruning level: '{level}'")
                return False
            return True
        except Exception as e:
            logger.error(f"[TaxonomyRepository] Failed to prune node '{name}' at level '{level}': {e}")
            return False
