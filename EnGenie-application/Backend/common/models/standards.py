"""Structured Pydantic models for engineering standards and standard specifications."""

import logging
from typing import Any, Iterator
from pydantic import Field, model_validator

from common.models.base import LenientModel, MongoModel

logger = logging.getLogger(__name__)


class TechnicalSpecifications(LenientModel):
    """Structured engineering standards specifications, covering all standard domains.

    Supports direct flat mapping of LLM extractions, with ConfigDict(extra="allow")
    to handle custom and legacy fields seamlessly.
    """

    @model_validator(mode="before")
    @classmethod
    def _coerce_and_normalize(cls, data: Any) -> Any:
        """Coerce list values to strings and dynamically map variations to camelCase properties."""
        if not isinstance(data, dict):
            return data
        
        # 1. Coerce list values into comma-separated strings
        for key, value in data.items():
            if isinstance(value, list):
                data[key] = ', '.join(str(v) for v in value if v is not None and str(v).strip())

        # 2. Dynamically build alias map from class fields
        field_map = {}
        for field_name in cls.model_fields.keys():
            field_map[field_name.lower()] = field_name
            spaced = "".join([" " + c if c.isupper() else c for c in field_name]).strip().lower()
            field_map[spaced] = field_name
            field_map[spaced.replace(" ", "_")] = field_name

        clean_data = {}
        for k, v in data.items():
            k_std = str(k).strip().lower().replace("-", " ").replace(".", " ")
            k_std = " ".join(k_std.split()) # normalize spaces
            
            if k_std in field_map:
                clean_data[field_map[k_std]] = v
            elif k_std.replace(" ", "") in field_map:
                clean_data[field_map[k_std.replace(" ", "")]] = v
            else:
                clean_data[k] = v

        return clean_data

    # --- ELECTRICAL ---
    supplyVoltage: str | None = None
    outputSignal: str | None = None
    powerConsumption: str | None = None
    loopImpedance: str | None = None
    currentConsumption: str | None = None
    cableEntry: str | None = None
    terminalType: str | None = None
    conduitSize: str | None = None
    groundingRequirement: str | None = None
    wireSize: str | None = None

    # --- COMMUNICATION ---
    communicationProtocol: str | None = None
    hartRevision: str | None = None
    fieldbusType: str | None = None
    baudRate: str | None = None
    deviceRevision: str | None = None
    analogOutput: str | None = None

    # --- ENVIRONMENTAL ---
    ipRating: str | None = None
    nemaRating: str | None = None
    ambientTemperature: str | None = None
    storageTemperature: str | None = None
    humidity: str | None = None
    vibrationResistance: str | None = None
    shockResistance: str | None = None

    # --- SAFETY ---
    silRating: str | None = None
    atexZone: str | None = None
    iecexRating: str | None = None
    necClassification: str | None = None
    explosionProtection: str | None = None
    fireSafeRating: str | None = None
    failSafeAction: str | None = None
    overpressureProtection: str | None = None
    burstPressure: str | None = None
    proofPressure: str | None = None

    # --- PROCESS CONDITIONS ---
    processTemperatureMin: str | None = None
    processTemperatureMax: str | None = None
    processPressureMin: str | None = None
    processPressureMax: str | None = None
    designPressure: str | None = None
    flowRateMin: str | None = None
    flowRateMax: str | None = None
    viscosityRange: str | None = None
    densityRange: str | None = None
    turndownRatio: str | None = None

    # --- MECHANICAL ---
    processConnection: str | None = None
    flangeRating: str | None = None
    flangeSize: str | None = None
    pipeSize: str | None = None
    endConnection: str | None = None
    faceToFaceDimension: str | None = None
    weight: str | None = None
    mounting: str | None = None
    orientation: str | None = None
    insertionDepth: str | None = None

    # --- MATERIALS ---
    bodyMaterial: str | None = None
    wettedMaterial: str | None = None
    gasketMaterial: str | None = None
    diaphragmMaterial: str | None = None
    housingMaterial: str | None = None
    linerMaterial: str | None = None
    electrodeMaterial: str | None = None
    trimMaterial: str | None = None
    packingMaterial: str | None = None
    seatMaterial: str | None = None
    sealMaterial: str | None = None
    oRingMaterial: str | None = None
    flangeMaterial: str | None = None
    tubingMaterial: str | None = None
    tubingSize: str | None = None
    manifoldMaterial: str | None = None
    valveSeatMaterial: str | None = None
    fittingMaterial: str | None = None
    cableMaterial: str | None = None
    enclosureMaterial: str | None = None
    junctionBoxMaterial: str | None = None

    # --- PERFORMANCE ---
    accuracy: str | None = None
    repeatability: str | None = None
    responseTime: str | None = None
    stability: str | None = None
    drift: str | None = None
    resolution: str | None = None
    sensitivity: str | None = None
    hysteresis: str | None = None
    deadBand: str | None = None
    leakageClass: str | None = None
    pressureDrop: str | None = None
    flowCoefficient: str | None = None

    # --- CERTIFICATIONS ---
    ceMarking: str | None = None
    atex: str | None = None
    iecex: str | None = None
    ul: str | None = None
    csa: str | None = None
    fm: str | None = None
    silCertification: str | None = None
    applicableStandard: str | None = None

    # --- INSTALLATION ---
    straightRunUpstream: str | None = None
    straightRunDownstream: str | None = None
    mountingMethod: str | None = None
    orientationRule: str | None = None
    slopeRequirement: str | None = None
    cableRouting: str | None = None
    cableSegregation: str | None = None
    cableBendRadius: str | None = None

    # --- MAINTENANCE ---
    calibrationInterval: str | None = None
    inspectionFrequency: str | None = None
    maintenanceInterval: str | None = None
    testingRequirement: str | None = None

    # --- HART INSTRUMENT ---
    damping: str | None = None
    faultAction: str | None = None
    driveGainLimit: str | None = None
    lowFlowCutoff: str | None = None
    smvFrequency: str | None = None
    electronicsLimit: str | None = None
    flowDirection: str | None = None
    totalizer: str | None = None
    primaryVariable: str | None = None
    secondaryVariable: str | None = None
    pvUnits: str | None = None
    urv: str | None = None
    lrv: str | None = None


class StandardDocument(MongoModel):
    """Pydantic model representing an engineering standards document in the collection."""

    user_id: int | str
    filename: str
    file_type: str | None = None
    full_text: str = ""
    technical_specifications: TechnicalSpecifications | None = None
    technical_specifications_error: str | None = None
    character_count: int = 0
    uploaded_at: str = ""
    blob_url: str | None = None


class StandardsCatalog(LenientModel):
    """Catalog holding a collection of standard documents, equipped with keyword scoring and matching."""

    documents: list[StandardDocument] = Field(default_factory=list)

    def find_best_match(self, category: str) -> StandardDocument | None:
        """Find the winning standard document for a category based on dynamic keyword scoring."""
        if not self.documents:
            return None

        # Clean category
        cat_norm = category.lower().strip()
        cat_keywords = cat_norm.split()

        # Dynamic keyword expansion
        expanded_keywords = []
        for kw in cat_keywords:
            expanded_keywords.append(kw)
            if len(kw) >= 5:
                expanded_keywords.append(kw[:4])
                expanded_keywords.append(kw[:5])
            if kw.endswith("er"):
                expanded_keywords.append(kw[:-2])
            if kw.endswith("or"):
                expanded_keywords.append(kw[:-2])
            if kw.endswith("ion"):
                expanded_keywords.append(kw[:-3])
            if kw.endswith("s") and len(kw) > 4:
                expanded_keywords.append(kw[:-1])
            elif not kw.endswith("s"):
                expanded_keywords.append(kw + "s")

        # De-duplicate keywords
        unique_kws = []
        seen = set()
        for kw in expanded_keywords:
            kw_clean = kw.strip()
            if kw_clean not in seen and len(kw_clean) >= 3:
                seen.add(kw_clean)
                unique_kws.append(kw_clean)

        logger.info(f"[StandardsCatalog] Matching keywords: {unique_kws}")

        # Compute document relevance scores
        scored_docs = []
        for doc in self.documents:
            filename = doc.filename.lower()
            score = 0
            matched_kws = []
            for kw in unique_kws:
                if kw in filename:
                    score += 5
                    matched_kws.append(kw)

            if score > 0:
                scored_docs.append((score, doc))

        # Return best match if found
        if scored_docs:
            scored_docs.sort(key=lambda x: x[0], reverse=True)
            best_score, best_doc = scored_docs[0]
            logger.info(f"[StandardsCatalog] Winner is '{best_doc.filename}' with score {best_score}")
            return best_doc

        # Best-effort fallback if user has exactly one document in catalog — but
        # only when we cannot positively rule it out. If the document's content is
        # available and never mentions any category keyword, do NOT apply an
        # unrelated standard to this item (prevents false "grounded" specs sourced
        # from a mismatched document).
        if len(self.documents) == 1:
            fallback = self.documents[0]
            content = (getattr(fallback, "full_text", "") or "").lower()
            if content and not any(kw in content for kw in unique_kws):
                logger.info(
                    f"[StandardsCatalog] Single doc '{fallback.filename}' content does not mention "
                    f"'{category}' — skipping fallback to avoid mismatched standards."
                )
                return None
            logger.warning(
                f"[StandardsCatalog] No keyword match for '{category}'. Falling back to single "
                f"available doc: {fallback.filename}"
            )
            return fallback

        logger.info(f"[StandardsCatalog] No matching standards document found for '{category}'")
        return None
