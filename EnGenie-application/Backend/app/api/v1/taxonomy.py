"""FastAPI routes for administrative and dynamic CRUD operations on the 4-level Taxonomy tree."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from common.helpers.responses import JSONResponse
from common.infra.repositories.taxonomy_repository import TaxonomyRepository
from common.models.taxonomy import ProductType, Product, ModelFamily, VendorProduct

logger = logging.getLogger(__name__)

blueprint = APIRouter()


@blueprint.get("/api/taxonomy/tree")
async def get_taxonomy_tree():
    """Fetch and return the complete hierarchical Taxonomy tree."""
    try:
        tax = TaxonomyRepository.get_full_taxonomy()
        return JSONResponse(tax.model_dump(exclude_none=True), status_code=status.HTTP_200_OK)
    except Exception as e:
        logger.exception(f"[TaxonomyAPI] Failed to retrieve tree: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve tree: {e}")


@blueprint.get("/api/taxonomy/resolve")
async def resolve_taxonomy_specifications(
    name: str = Query(..., description="The canonical name or alias of the node to resolve specs for")
):
    """Dynamically resolve specifications for a taxonomy node, merging and cascading specs from parents down to leaves."""
    try:
        tax = TaxonomyRepository.get_full_taxonomy()
        resolved = tax.resolve_specifications(name)
        if not resolved:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Specifications could not be resolved for '{name}'. Node not found or has no specs."
            )
        return JSONResponse(
            {"name": name, "resolved_specifications": resolved},
            status_code=status.HTTP_200_OK
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[TaxonomyAPI] Failed to resolve specs for '{name}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@blueprint.post("/api/taxonomy/product-types", status_code=status.HTTP_201_CREATED)
async def create_product_type(pt: ProductType):
    """Idempotently insert a new top-level ProductType subtree document."""
    success = TaxonomyRepository.add_product_type(pt)
    if not success:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to insert ProductType")
    return JSONResponse(
        {"success": True, "message": f"ProductType '{pt.name}' created successfully"},
        status_code=status.HTTP_201_CREATED
    )


@blueprint.post("/api/taxonomy/products", status_code=status.HTTP_201_CREATED)
async def create_product(
    product_type: str = Query(..., description="Parent ProductType name"),
    p: Product = ...
):
    """Idempotently and atomically append a new Product to a ProductType."""
    success = TaxonomyRepository.add_product(product_type, p)
    if not success:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to add Product")
    return JSONResponse(
        {"success": True, "message": f"Product '{p.name}' appended to ProductType '{product_type}'"},
        status_code=status.HTTP_201_CREATED
    )


@blueprint.post("/api/taxonomy/model-families", status_code=status.HTTP_201_CREATED)
async def create_model_family(
    product_type: str = Query(..., description="Parent ProductType name"),
    product: str = Query(..., description="Parent Product name"),
    mf: ModelFamily = ...
):
    """Idempotently and atomically append a new ModelFamily to a Product."""
    success = TaxonomyRepository.add_model_family(product_type, product, mf)
    if not success:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to add ModelFamily")
    return JSONResponse(
        {"success": True, "message": f"ModelFamily '{mf.name}' appended to Product '{product}'"},
        status_code=status.HTTP_201_CREATED
    )


@blueprint.post("/api/taxonomy/vendor-products", status_code=status.HTTP_201_CREATED)
async def create_vendor_product(
    product_type: str = Query(..., description="Parent ProductType name"),
    product: str = Query(..., description="Parent Product name"),
    family: str = Query(..., description="Parent ModelFamily name"),
    vp: VendorProduct = ...
):
    """Idempotently and atomically append a new VendorProduct to a ModelFamily."""
    success = TaxonomyRepository.add_vendor_product(product_type, product, family, vp)
    if not success:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to add VendorProduct")
    return JSONResponse(
        {"success": True, "message": f"VendorProduct '{vp.name}' appended to ModelFamily '{family}'"},
        status_code=status.HTTP_201_CREATED
    )


@blueprint.delete("/api/taxonomy/node")
async def prune_taxonomy_node(
    level: str = Query(..., description="The hierarchy level to delete from (product_type, product, model_family, vendor_product)"),
    name: str = Query(..., description="The name of the node to prune from the tree")
):
    """Idempotently prune/delete a specific taxonomy sub-tree node by its name and hierarchy tier."""
    success = TaxonomyRepository.delete_node(level, name)
    if not success:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to prune node '{name}'")
    return JSONResponse(
        {"success": True, "message": f"Pruned taxonomy node '{name}' at level '{level}'"},
        status_code=status.HTTP_200_OK
    )
