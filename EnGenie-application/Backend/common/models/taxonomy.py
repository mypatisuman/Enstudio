"""Hierarchical Pydantic taxonomy: ProductType -> Product -> ModelFamily -> VendorProduct."""

from typing import Any, Iterator

from pydantic import BaseModel, ConfigDict, Field, field_validator


_BASE_CONFIG = ConfigDict(
    extra="allow",
    populate_by_name=True,
    str_strip_whitespace=True,
    protected_namespaces=(),
)


def _normalize_aliases(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        value = [value]
    return sorted({str(a).strip().lower() for a in value if str(a).strip()})


_PARAMETER_ALIASES = {
    "body_material": ["body mat", "body material", "materials of construction", "wetted material", "material", "body_material"],
    "accuracy": ["acc", "instrument accuracy", "accuracy class", "calibrated accuracy", "accuracy"],
    "flange_material": ["flg mat", "flange material", "flg material", "flange_material"],
    "lining_material": ["lining mat", "lining material", "tube lining", "lining_material"],
    "electrode_material": ["electrode mat", "electrode material", "electrodes", "electrode_material"],
    "output_protocol": ["protocol", "output", "signal output", "communication", "output_protocol"],
    "static_pressure_limit": ["static limit", "static pressure", "static pressure limit", "pressure limit", "static_pressure_limit"],
    "pipe_size": ["size", "pipe size", "nominal size", "diameter", "pipe_size"]
}


class VendorProduct(BaseModel):
    """Specific vendor submodel (e.g. 'Rosemount 3051CD')."""
    model_config = _BASE_CONFIG

    name: str
    vendor: str
    aliases: list[str] = Field(default_factory=list)
    specifications: dict[str, Any] = Field(default_factory=dict)
    certifications: list[str] = Field(default_factory=list)
    datasheet_url: str | None = None
    description: str = ""

    @field_validator("aliases", mode="before")
    @classmethod
    def _norm(cls, v): return _normalize_aliases(v)

    def matches(self, text: str) -> bool:
        t = text.strip().lower()
        return t == self.name.lower() or t in self.aliases

    def merge_specifications(self, extra: dict[str, Any]) -> None:
        for k, v in (extra or {}).items():
            if v is not None and k not in self.specifications:
                self.specifications[k] = v


class ModelFamily(BaseModel):
    """Vendor product family/series (e.g. '3051C series')."""
    model_config = _BASE_CONFIG

    name: str
    vendor: str = ""
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    shared_specifications: dict[str, Any] = Field(default_factory=dict)
    vendor_products: list[VendorProduct] = Field(default_factory=list)

    @field_validator("aliases", mode="before")
    @classmethod
    def _norm(cls, v): return _normalize_aliases(v)

    def matches(self, text: str) -> bool:
        t = text.strip().lower()
        return t == self.name.lower() or t in self.aliases

    def find_vendor_product(self, name_or_alias: str) -> VendorProduct | None:
        return next((vp for vp in self.vendor_products if vp.matches(name_or_alias)), None)

    def add_vendor_product(self, vp: VendorProduct) -> VendorProduct:
        existing = self.find_vendor_product(vp.name)
        if existing:
            return existing
        self.vendor_products.append(vp)
        return vp

    def alias_index(self) -> dict[str, str]:
        idx: dict[str, str] = {self.name.lower(): self.name}
        for a in self.aliases:
            idx[a] = self.name
        for vp in self.vendor_products:
            idx[vp.name.lower()] = vp.name
            for a in vp.aliases:
                idx[a] = vp.name
        return idx


class Product(BaseModel):
    """Sub-category of a ProductType (e.g. 'Differential Pressure Transmitter')."""
    model_config = _BASE_CONFIG

    name: str
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    default_specifications: dict[str, Any] = Field(default_factory=dict)
    model_families: list[ModelFamily] = Field(default_factory=list)

    @field_validator("aliases", mode="before")
    @classmethod
    def _norm(cls, v): return _normalize_aliases(v)

    def matches(self, text: str) -> bool:
        t = text.strip().lower()
        return t == self.name.lower() or t in self.aliases

    def find_model_family(self, name_or_alias: str) -> ModelFamily | None:
        return next((mf for mf in self.model_families if mf.matches(name_or_alias)), None)

    def add_model_family(self, mf: ModelFamily) -> ModelFamily:
        existing = self.find_model_family(mf.name)
        if existing:
            return existing
        self.model_families.append(mf)
        return mf

    def alias_index(self) -> dict[str, str]:
        idx: dict[str, str] = {self.name.lower(): self.name}
        for a in self.aliases:
            idx[a] = self.name
        for mf in self.model_families:
            idx.update(mf.alias_index())
        return idx


class ProductType(BaseModel):
    """Top of the hierarchy (e.g. 'Pressure Transmitter')."""
    model_config = _BASE_CONFIG

    name: str
    canonical_name: str | None = None
    category: str = ""
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    schema_url: str | None = None
    products: list[Product] = Field(default_factory=list)

    @field_validator("aliases", mode="before")
    @classmethod
    def _norm(cls, v): return _normalize_aliases(v)

    @property
    def display_name(self) -> str:
        return self.canonical_name or self.name

    def matches(self, text: str) -> bool:
        t = text.strip().lower()
        if t == self.name.lower():
            return True
        if self.canonical_name and t == self.canonical_name.lower():
            return True
        return t in self.aliases

    def find_product(self, name_or_alias: str) -> Product | None:
        return next((p for p in self.products if p.matches(name_or_alias)), None)

    def add_product(self, p: Product) -> Product:
        existing = self.find_product(p.name)
        if existing:
            return existing
        self.products.append(p)
        return p

    def alias_index(self) -> dict[str, str]:
        idx: dict[str, str] = {self.name.lower(): self.display_name}
        if self.canonical_name:
            idx[self.canonical_name.lower()] = self.display_name
        for a in self.aliases:
            idx[a] = self.display_name
        for p in self.products:
            idx.update(p.alias_index())
        return idx

    def to_mongo_doc(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=False)

    @classmethod
    def from_mongo_doc(cls, doc: dict[str, Any]) -> "ProductType":
        clean = {k: v for k, v in doc.items() if not str(k).startswith("_")}
        return cls.model_validate(clean)


class Taxonomy(BaseModel):
    """Root container for the full 4-level taxonomy tree."""
    model_config = _BASE_CONFIG

    product_types: list[ProductType] = Field(default_factory=list)

    def get_product_type(self, name_or_alias: str) -> ProductType | None:
        return next((pt for pt in self.product_types if pt.matches(name_or_alias)), None)

    def add_product_type(self, pt: ProductType) -> ProductType:
        existing = self.get_product_type(pt.name)
        if existing:
            return existing
        self.product_types.append(pt)
        return pt

    def find(self, name_or_alias: str) -> tuple[str, BaseModel] | None:
        """Deepest-wins lookup across all 4 levels. Returns (level, object) or None."""
        t = name_or_alias.strip().lower()
        for pt in self.product_types:
            for p in pt.products:
                for mf in p.model_families:
                    for vp in mf.vendor_products:
                        if t == vp.name.lower() or t in vp.aliases:
                            return ("vendor_product", vp)
                    if mf.matches(t):
                        return ("model_family", mf)
                if p.matches(t):
                    return ("product", p)
            if pt.matches(t):
                return ("product_type", pt)
        return None

    def find_path(self, name_or_alias: str) -> list[BaseModel] | None:
        """Find the full hierarchical path to the deepest matching node.

        Returns e.g. [ProductType, Product, ModelFamily, VendorProduct] or None.
        """
        t = name_or_alias.strip().lower()
        for pt in self.product_types:
            for p in pt.products:
                for mf in p.model_families:
                    for vp in mf.vendor_products:
                        if t == vp.name.lower() or t in vp.aliases:
                            return [pt, p, mf, vp]
                    if mf.matches(t):
                        return [pt, p, mf]
                if p.matches(t):
                    return [pt, p]
            if pt.matches(t):
                return [pt]
        return None

    def resolve_specifications(self, name_or_alias: str) -> dict[str, Any]:
        """Resolves specifications for a node by cascading default/shared specs from parents.

        Spec hierarchy: Product default_specifications -> ModelFamily shared_specifications -> VendorProduct specifications.
        """
        path = self.find_path(name_or_alias)
        if not path:
            return {}

        resolved: dict[str, Any] = {}
        for node in path:
            if isinstance(node, Product):
                for k, v in (node.default_specifications or {}).items():
                    if v is not None:
                        resolved[k] = v
            elif isinstance(node, ModelFamily):
                for k, v in (node.shared_specifications or {}).items():
                    if v is not None:
                        resolved[k] = v
            elif isinstance(node, VendorProduct):
                for k, v in (node.specifications or {}).items():
                    if v is not None:
                        resolved[k] = v
        return resolved

    def normalize_parameter_keys(self, matched_canonical_name: str, raw_extracted_specs: dict[str, Any]) -> dict[str, Any]:
        """Dynamically normalizes and maps raw key-value parameter specifications to canonical fields.

        Uses a two-pass matching process:
        1. Explicit alias mapping using the global _PARAMETER_ALIASES registry.
        2. Fuzzy string matching using Levenshtein distance against known specs in the node path.
        """
        path = self.find_path(matched_canonical_name)
        if not path or not raw_extracted_specs:
            return raw_extracted_specs

        # Compile all valid canonical specification keys for the matching hierarchy path
        allowed_canonical_keys: set[str] = set()
        for node in path:
            if isinstance(node, Product):
                allowed_canonical_keys.update((node.default_specifications or {}).keys())
            elif isinstance(node, ModelFamily):
                allowed_canonical_keys.update((node.shared_specifications or {}).keys())
            elif isinstance(node, VendorProduct):
                allowed_canonical_keys.update((node.specifications or {}).keys())

        # If we didn't find any allowed specs in the path, use the global keys as fallback
        if not allowed_canonical_keys:
            allowed_canonical_keys = set(_PARAMETER_ALIASES.keys())

        normalized: dict[str, Any] = {}
        for raw_k, val in raw_extracted_specs.items():
            k_std = str(raw_k).strip().lower().replace("_", " ")
            mapped_key = None

            # Pass 1: Check explicit aliases
            for canonical, aliases in _PARAMETER_ALIASES.items():
                if k_std == canonical or k_std in aliases:
                    mapped_key = canonical
                    break

            # Pass 2: Fallback to fuzzy string matching (Levenshtein)
            if not mapped_key:
                from difflib import get_close_matches
                # Compare k_std to allowed canonical keys
                matches = get_close_matches(k_std, list(allowed_canonical_keys), n=1, cutoff=0.75)
                if matches:
                    mapped_key = matches[0]

            if mapped_key:
                normalized[mapped_key] = val
            else:
                # If no match, preserve original raw key so we don't drop custom data
                normalized[raw_k] = val

        return normalized

    def flat_alias_index(self) -> dict[str, str]:
        """Combined alias->canonical map across all levels (compatible with TaxonomyNormalizationAgent).

        Two-pass: auto-derived canonical-name keys first, then explicit aliases overlaid so an
        explicit alias always wins a collision with a name (matches the legacy flattening, where
        only alias keys exist). Names are still added so queries by canonical name resolve.
        """
        names: dict[str, str] = {}
        aliases: dict[str, str] = {}
        for pt in self.product_types:
            cv = pt.display_name
            names[pt.name.lower()] = cv
            if pt.canonical_name:
                names[pt.canonical_name.lower()] = cv
            for a in pt.aliases:
                aliases[a] = cv
            for p in pt.products:
                names[p.name.lower()] = p.name
                for a in p.aliases:
                    aliases[a] = p.name
                for mf in p.model_families:
                    names[mf.name.lower()] = mf.name
                    for a in mf.aliases:
                        aliases[a] = mf.name
                    for vp in mf.vendor_products:
                        names[vp.name.lower()] = vp.name
                        for a in vp.aliases:
                            aliases[a] = vp.name
        return {**names, **aliases}

    def iter_leaves(self) -> Iterator[tuple[ProductType, Product, ModelFamily, VendorProduct]]:
        for pt in self.product_types:
            for p in pt.products:
                for mf in p.model_families:
                    for vp in mf.vendor_products:
                        yield (pt, p, mf, vp)

    def stats(self) -> dict[str, int]:
        product_count = sum(len(pt.products) for pt in self.product_types)
        family_count = sum(len(p.model_families) for pt in self.product_types for p in pt.products)
        vendor_product_count = sum(
            len(mf.vendor_products)
            for pt in self.product_types
            for p in pt.products
            for mf in p.model_families
        )
        return {
            "product_types": len(self.product_types),
            "products": product_count,
            "model_families": family_count,
            "vendor_products": vendor_product_count,
        }

    def to_mongo_docs(self) -> list[dict[str, Any]]:
        """One MongoDB doc per top-level ProductType (full sub-tree included)."""
        return [pt.to_mongo_doc() for pt in self.product_types]

    @classmethod
    def from_mongo_docs(cls, docs: list[dict[str, Any]]) -> "Taxonomy":
        return cls(product_types=[ProductType.from_mongo_doc(d) for d in docs])

    @classmethod
    def from_aliases_json(cls, data: dict[str, Any]) -> "Taxonomy":
        """Hydrate from the legacy {CATEGORY: {alias: canonical}} JSON shape."""
        grouped: dict[tuple[str, str], list[str]] = {}
        for category, mapping in (data or {}).items():
            if not isinstance(mapping, dict):
                continue
            for alias, canonical in mapping.items():
                if not alias or not canonical:
                    continue
                grouped.setdefault((str(category).upper(), str(canonical)), []).append(str(alias))
        product_types = [
            ProductType(
                name=canonical,
                canonical_name=canonical,
                category=category,
                aliases=aliases,
            )
            for (category, canonical), aliases in grouped.items()
        ]
        return cls(product_types=product_types)

    @classmethod
    def from_flat_alias_docs(cls, docs: list[dict[str, Any]]) -> "Taxonomy":
        """Hydrate from the legacy MongoDB 'taxonomy' collection shape: [{type, alias, canonical, category?}]."""
        grouped: dict[tuple[str, str], list[str]] = {}
        for d in docs or []:
            canonical = d.get("canonical")
            alias = d.get("alias")
            if not canonical or not alias:
                continue
            category = str(d.get("category", "")).upper()
            grouped.setdefault((category, str(canonical)), []).append(str(alias))
        product_types = [
            ProductType(
                name=canonical,
                canonical_name=canonical,
                category=category,
                aliases=aliases,
            )
            for (category, canonical), aliases in grouped.items()
        ]
        return cls(product_types=product_types)
