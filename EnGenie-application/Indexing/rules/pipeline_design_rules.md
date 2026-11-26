# 5-Tier Pipeline Data Architecture & Design Rules

This document outlines the core rules, definitions, and templates governing specifications ingestion across **Equipments** and **Accessories** in the 5-Tier catalog hierarchy.

---

## 1. Node Classifications & Value Enrichment Rules

| Node Type | Definition | Catalog Values Policy | Ingestion Behavior |
| :--- | :--- | :--- | :--- |
| **Equipment** | Primary process control instruments (e.g. Transmitters, Flow Meters, Sensors). | **Null Templates** (`value: null`) | Values must remain `null` to serve as a clean schema shell for downstream models. |
| **Accessory** | Supplementary parts and hardware (e.g. brackets, manifolds, cables, flanges). | **Enriched Values** (`value: "Banana Plugs"`) | Values must be parsed and populated during catalog updates to facilitate inventory match-making. |

### Enriched vs. Null Logic in Code:
In the update phase, the pipeline explicitly filters out Equipments:
```python
ntype = node.get("type", "Equipment")
if ntype != "Accessory":
    continue  # Equipments remain unpopulated schemas
```

---

## 2. Dual-Schema Specifications Architecture

When creating or modifying specifications for **L0, L1, or L2** taxonomy levels, two parallel fields must be populated at the document root to preserve backward-compatibility with older RAG/validation clients while supporting modern typed schemas.

### A. Legacy Parameters Structure (`parameters`)
A flat object split into three distinct importance tiers:
```json
"parameters": {
  "mandatoryRequirements": {
    "process_connections": null
  },
  "optionalRequirements": {
    "mounting_position_effect": null
  },
  "latestRequirements": {
    "cybersecurity_hardening": null
  },
  "units": {
    "operating_pressure": "bar"
  }
}
```

### B. Modern Grouped Structure (`specifications`)
A nested structure categorized by engineering domains where each category maps to an object wrapping a `"parameters"` list of SpecParameter entries:
```json
"specifications": {
  "id": "SPEC-C16-P11-S01",
  "safety": {
    "parameters": [
      {
        "id": "SF-1",
        "name": "Intrinsic Safety Rating",
        "value": "Ex ia IIC T4 Ga",
        "level": "Optional",
        "units": null,
        "type": "certification"
      }
    ]
  },
  "electrical": {
    "parameters": [ ... ]
  }
}
```

---

## 3. Mapping Reference Rules

### Tier to Parameter Level Mapping:
* `mandatoryRequirements` ➔ `"Required"`
* `optionalRequirements` ➔ `"Optional"`
* `latestRequirements` ➔ `"Advanced"`

### Spec Category Prefixes:
* `safety` ➔ `"SF"`
* `electrical` ➔ `"EL"`
* `mechanical` ➔ `"MC"`
* `process` ➔ `"PR"`
* `environmental` ➔ `"EN"`
* `performance` ➔ `"PF"`
* `certifications` ➔ `"CT"`
* `materials` ➔ `"MT"`
* `communication` ➔ `"CM"`
* `product_info` ➔ `"PI"`
* `applications` ➔ `"AP"`
