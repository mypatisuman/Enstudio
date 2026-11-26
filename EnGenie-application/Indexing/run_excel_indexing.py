"""
Parallel Multi-Threaded Batch Indexing Pipeline for MongoDB_Instruments_and_Accessories.xlsx
Powered by Ollama on Mac Mini (http://192.168.0.113:11434)

Workflow:
1. Probes Mac Mini Ollama connectivity.
2. Extracts unique L1 Product Types from Excel sheets ('All Instruments' & 'All Accessories').
3. Queries MongoDB 'advanced_specifications' to identify missing items.
4. Uses ThreadPoolExecutor (multi-threading) to process missing items concurrently via Mac Mini Ollama.
"""
import os
import sys
import logging
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

# Setup paths
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.abspath(os.path.join(_HERE, "..", "Backend"))

if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

load_dotenv(os.path.join(_HERE, ".env"), override=True)
load_dotenv(os.path.join(_BACKEND, ".env"), override=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("excel_indexer")

from common.ai.llm.providers.ollama import get_active_ollama_base_url, _is_host_reachable
from common.infra.mongodb_config import get_mongodb_connection
from advanced_specs import process_single_product, _norm


def clean(v):
    s = str(v).strip()
    return "" if s.lower() in ("", "nan", "none") else s


def _process_product_worker(product: str, idx: int, total: int, db) -> tuple[str, str, str]:
    log.info("[%d/%d] 🚀 Started processing: '%s'...", idx, total, product)
    try:
        res = process_single_product(product_type=product, parameters={}, db=db)
        if res:
            log.info("[%d/%d] ✅ Successfully indexed '%s'", idx, total, product)
            return product, "success", ""
        else:
            log.info("[%d/%d] ⏭️ Skipped '%s' (already cached or empty)", idx, total, product)
            return product, "skipped", ""
    except Exception as e:
        log.error("[%d/%d] ❌ Failed to index '%s': %s", idx, total, product, e)
        return product, "failed", str(e)


def main(limit: int = 0, max_workers: int = 4):
    log.info("=== STEP 1: Testing Ollama Accessibility on Mac Mini ===")
    url = get_active_ollama_base_url()
    log.info("Target Ollama URL: %s", url)
    
    if not _is_host_reachable(url, timeout=5.0):
        log.error("🛑 Host %s is UNREACHABLE! Please verify Mac Mini is running 'OLLAMA_HOST=0.0.0.0:11434 ollama serve'.", url)
        sys.exit(1)
        
    log.info("✅ Mac Mini Ollama server is UP and REACHABLE!")

    log.info("=== STEP 2: Loading Excel Catalog ===")
    excel_path = os.path.join(os.path.dirname(_HERE), "MongoDB_Instruments_and_Accessories.xlsx")
    if not os.path.exists(excel_path):
        excel_path = os.path.join(_HERE, "MongoDB_Instruments_and_Accessories.xlsx")
        
    log.info("Using spreadsheet: %s", excel_path)
    xl = pd.ExcelFile(excel_path)
    
    all_products = set()
    for sheet in ["All Instruments", "All Accessories"]:
        if sheet in xl.sheet_names:
            df = pd.read_excel(excel_path, sheet_name=sheet)
            for _, r in df.iterrows():
                l1 = clean(r.get("L1 Product Type") or r.get("Product") or r.get("Device"))
                if l1:
                    all_products.add(l1)
                    
    sorted_products = sorted(list(all_products))
    log.info("Found %d unique L1 Product Types in Excel catalog.", len(sorted_products))

    log.info("=== STEP 3: Checking MongoDB Indexing Status ===")
    db = get_mongodb_connection()["database"]
    adv_col = db["advanced_specifications"]
    
    already_indexed = set(adv_col.distinct("product_type"))
    already_indexed_norm = {s.lower().replace(" ", "").replace("_", "") for s in already_indexed}
    
    missing_products = [
        p for p in sorted_products 
        if p.lower().replace(" ", "").replace("_", "") not in already_indexed_norm
    ]
    
    log.info("Currently indexed in MongoDB: %d", len(already_indexed))
    log.info("Missing Product Types to index: %d", len(missing_products))
    
    if not missing_products:
        log.info("🎉 All products are already indexed! Nothing to do.")
        return

    if limit > 0:
        log.info("Running with limit=%d (Processing first %d missing products)", limit, limit)
        missing_products = missing_products[:limit]

    total = len(missing_products)
    log.info("=== STEP 4: Starting Parallel Batch Indexing (Workers=%d) via Mac Mini Ollama ===", max_workers)
    
    success_count = 0
    skip_count = 0
    fail_count = 0
    
    start_time = datetime.now()
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_product = {
            executor.submit(_process_product_worker, product, idx, total, db): product
            for idx, product in enumerate(missing_products, start=1)
        }
        
        for future in as_completed(future_to_product):
            product, status, err = future.result()
            if status == "success":
                success_count += 1
            elif status == "skipped":
                skip_count += 1
            else:
                fail_count += 1
                
    elapsed = (datetime.now() - start_time).total_seconds()
    log.info("=== PARALLEL INDEXING COMPLETED in %.2f seconds (%.2f min) ===", elapsed, elapsed / 60.0)
    log.info("Total Processed: %d | Success: %d | Skipped: %d | Failed: %d", total, success_count, skip_count, fail_count)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Parallel batch index products from Excel via Mac Mini Ollama")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of items to process (0 = process all missing)")
    parser.add_argument("--workers", type=int, default=4, help="Number of concurrent thread workers (default: 4)")
    args = parser.parse_args()
    
    main(limit=args.limit, max_workers=args.workers)
