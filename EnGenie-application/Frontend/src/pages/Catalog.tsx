import React, { useState, useEffect, useRef, useCallback } from "react";
import axios from "axios";
import { useNavigate, useLocation } from "react-router-dom";
import MainHeader from "@/components/MainHeader";
import { BASE_URL } from "@/components/AIRecommender/api";
import {
    Database, Loader2, Search, X, Package,
    ChevronRight, Building2, ImageOff,
    ChevronDown, Tag, ArrowLeft,
} from "lucide-react";

interface VendorData {
    name: string;
    modelFamilies: string[];
}

interface ProductTypeSummary {
    name: string;
    vendorCount: number;
    modelCount: number;
}

interface ProductTypeDetailed {
    name: string;
    vendors: VendorData[];
    totalVendors: number;
    totalModelFamilies: number;
}

interface ImageState {
    url: string | null;
    loading: boolean;
}

const imageCache = new Map<string, ImageState>();

// ── Helper function for proper capitalization ─────────────────────────────
const capitalizeFirst = (text: string): string => {
    if (!text) return text;
    return text.charAt(0).toUpperCase() + text.slice(1).toLowerCase();
};

// ── Model card with lazy-loaded image ─────────────────────────────────────
function ModelCard({ vendor, model, productType, listMode }: { vendor: string; model: string; productType: string; listMode: boolean }) {
    const key = `${vendor}::${productType}::${model}`;
    const [img, setImg] = useState<ImageState>(imageCache.get(key) ?? { url: null, loading: true });
    const cardRef = useRef<HTMLDivElement>(null);
    const fetched = useRef(false);

    const fetchImage = useCallback(async () => {
        if (fetched.current) return;
        fetched.current = true;
        try {
            const res = await axios.get('/api/catalog-image', { params: { vendor, model, product_type: productType } });
            const data = res.data;
            const next: ImageState = data.found && data.image_url
                ? { url: data.image_url, loading: false }
                : { url: null, loading: false };
            imageCache.set(key, next);
            setImg(next);
        } catch {
            const next: ImageState = { url: null, loading: false };
            imageCache.set(key, next);
            setImg(next);
        }
    }, [vendor, model, productType, key]);

    useEffect(() => {
        const el = cardRef.current;
        if (!el) return;
        if (imageCache.has(key)) { setImg(imageCache.get(key)!); return; }
        const obs = new IntersectionObserver(entries => {
            if (entries[0].isIntersecting) { fetchImage(); obs.disconnect(); }
        }, { rootMargin: "200px" });
        obs.observe(el);
        return () => obs.disconnect();
    }, [key, fetchImage]);

    const imgEl = img.loading
        ? <Loader2 className="w-5 h-5 text-primary animate-spin" />
        : img.url
            ? <img src={img.url} alt={model} className="max-w-full max-h-full object-contain transition-transform duration-300"
                onError={() => setImg({ url: null, loading: false })} />
            : <div className="flex flex-col items-center gap-0.5 text-muted-foreground/40">
                <ImageOff className="w-5 h-5" /><span className="text-[9px]">No image</span>
            </div>;

    if (listMode) return (
        <div ref={cardRef} className="flex items-center gap-3 px-4 py-3 hover:bg-white/5 hover:scale-[1.02] transition-all duration-200 cursor-default group">
            <div className="w-10 h-10 rounded-lg overflow-hidden shrink-0 bg-[#212121] border border-white/10 flex items-center justify-center backdrop-blur-sm">
                {imgEl}
            </div>
            <span className="text-base text-foreground font-medium">{capitalizeFirst(model)}</span>
        </div>
    );

    return (
        <div ref={cardRef} className="glass-card group flex flex-col rounded-xl shadow-sm hover:shadow-lg hover:-translate-y-0.5 hover:scale-[1.03] overflow-hidden cursor-default transition-all duration-200">
            <div className="h-36 bg-[#171717] flex items-center justify-center overflow-hidden border-b border-white/10 p-4">
                <div className="w-full h-full flex items-center justify-center">
                    {imgEl}
                </div>
            </div>
            <div className="px-3 py-3"><p className="text-base font-semibold text-foreground leading-snug line-clamp-2">{capitalizeFirst(model)}</p></div>
        </div>
    );
}

// ── Vendor section (collapsible) ─────────────────────────────────────
function VendorSection({ vendor, productType, viewMode, defaultOpen }: {
    vendor: VendorData; productType: string; viewMode: "grid" | "list"; defaultOpen: boolean;
}) {
    const [open, setOpen] = useState(defaultOpen);
    const [search, setSearch] = useState("");

    const filtered = vendor.modelFamilies.filter(mf =>
        mf.toLowerCase().includes(search.toLowerCase())
    );

    return (
        <div className="mb-5">
            {/* Vendor header */}
            <button
                onClick={() => setOpen(o => !o)}
                className="w-full flex items-center gap-3 mb-3 group"
            >
                <div className="flex items-center gap-3 flex-1 min-w-0">
                    <Building2 className="w-5 h-5 text-sky-400 shrink-0" />
                    <h3 className="text-lg font-bold text-foreground truncate">{capitalizeFirst(vendor.name)}</h3>
                    <span className="text-sm bg-sky-500/10 text-sky-400 px-3 py-1 rounded-full font-medium shrink-0">
                        {vendor.modelFamilies.length} models
                    </span>
                </div>
                <div className={`text-muted-foreground transition-transform duration-200 ${open ? "rotate-0" : "-rotate-90"}`}>
                    <ChevronDown className="w-5 h-5" />
                </div>
            </button>

            {open && (
                <div>
                    {/* Mini search inside vendor */}
                    {vendor.modelFamilies.length > 6 && (
                        <div className="relative mb-3">
                            <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500 pointer-events-none" />
                            <input
                                type="text"
                                placeholder={`Filter ${capitalizeFirst(vendor.name)} models...`}
                                value={search}
                                onChange={e => setSearch(e.target.value)}
                                className="w-full pl-7 pr-8 py-2.5 text-sm rounded-lg bg-[#212121] border border-white/10 text-foreground placeholder:text-zinc-500 focus:outline-none focus:ring-1 focus:ring-sky-500/40 backdrop-blur-sm hover:scale-[1.02] transition-all duration-200"
                            />
                            {search && <button onClick={() => setSearch("")} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-white"><X className="w-4 h-4" /></button>}
                        </div>
                    )}

                    {filtered.length === 0 ? (
                        <p className="text-sm text-muted-foreground px-2 py-3">No results.</p>
                    ) : viewMode === "list" ? (
                        <div className="bg-[#171717] rounded-xl border border-white/10 overflow-hidden divide-y divide-white/10 backdrop-blur-sm">
                            {filtered.map(mf => (
                                <ModelCard key={`${vendor.name}::${mf}`} vendor={vendor.name} model={mf} productType={productType} listMode />
                            ))}
                        </div>
                    ) : (
                        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
                            {filtered.map(mf => (
                                <ModelCard key={`${vendor.name}::${mf}`} vendor={vendor.name} model={mf} productType={productType} listMode={false} />
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* Divider */}
            <div className="h-px bg-white/30 dark:bg-slate-700/40 mt-4" />
        </div>
    );
}

// ── Parallel prefetch with concurrency cap ────────────────────────────────
// Fires one request per product type; runs at most `concurrency` at a time.
// Stores results in cache and patches sidebar counts as they arrive.
function prefetchAll(
    productTypes: ProductTypeSummary[],
    cache: Map<string, ProductTypeDetailed>,
    setProductTypes: React.Dispatch<React.SetStateAction<ProductTypeSummary[]>>,
    concurrency = 10
) {
    let index = 0;
    let active = 0;

    function next() {
        while (active < concurrency && index < productTypes.length) {
            const pt = productTypes[index++];
            active++;
            axios.get(`/api/catalog-vendors/${encodeURIComponent(pt.name)}`)
                .then(r => {
                    const data: ProductTypeDetailed = r.data;
                    cache.set(pt.name, data);
                    if (data.totalVendors > 0 || data.totalModelFamilies > 0) {
                        setProductTypes(prev => prev.map(p =>
                            p.name === pt.name
                                ? { ...p, vendorCount: data.totalVendors, modelCount: data.totalModelFamilies }
                                : p
                        ));
                    }
                })
                .catch(() => {})
                .finally(() => { active--; next(); });
        }
    }

    next();
}

// ── Main Catalog Page ───────────────────────────────────────────────────────
export default function Catalog() {
    const navigate = useNavigate();
    const location = useLocation();
    const [loading, setLoading] = useState(true);
    const [productTypes, setProductTypes] = useState<ProductTypeSummary[]>([]);
    const [selectedProductType, setSelectedProductType] = useState<ProductTypeSummary | null>(null);
    const [selectedProductTypeDetails, setSelectedProductTypeDetails] = useState<ProductTypeDetailed | null>(null);
    const [loadingVendors, setLoadingVendors] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const viewMode = "grid";
    const [productTypeSearch, setProductTypeSearch] = useState("");
    const [vendorSearch, setVendorSearch] = useState("");
    const contentRef = useRef<HTMLDivElement>(null);

    // Prefetch map: populated in background after product types load.
    // Keys are product type names; values are the catalog-vendors responses.
    const prefetchCache = useRef<Map<string, ProductTypeDetailed>>(new Map());

    // Get the previous location from navigation state
    const fromLocation = (location.state as any)?.from;
    const preserveState = (location.state as any)?.preserveState;

    // Initial load: fetch product types, then immediately kick off parallel
    // prefetch of all vendor details so clicks are instant.
    useEffect(() => {
        const controller = new AbortController();
        axios.get('/api/catalog-product-types', { signal: controller.signal })
            .then(r => {
                const data = r.data;
                setProductTypes(data.productTypes);
                if (data.productTypes.length > 0) {
                    setSelectedProductType(data.productTypes[0]);
                }
                // Prefetch all vendor details in parallel with a concurrency cap
                // so the backend isn't flooded. Results land in prefetchCache as
                // they arrive — clicking any product type becomes instant.
                prefetchAll(data.productTypes, prefetchCache.current, setProductTypes);
            })
            .catch(e => { if (e.name !== 'AbortError') setError(e.message); })
            .finally(() => setLoading(false));
        return () => controller.abort();
    }, []);

    // When a product type is selected: serve from prefetch cache if ready,
    // otherwise fall back to a live fetch (shows spinner).
    useEffect(() => {
        if (!selectedProductType) return;

        const cached = prefetchCache.current.get(selectedProductType.name);
        if (cached) {
            setSelectedProductTypeDetails(cached);
            setLoadingVendors(false);
            return;
        }

        const controller = new AbortController();
        setLoadingVendors(true);
        axios.get(`/api/catalog-vendors/${encodeURIComponent(selectedProductType.name)}`, { signal: controller.signal })
            .then(r => {
                const data = r.data;
                prefetchCache.current.set(selectedProductType.name, data);
                setSelectedProductTypeDetails(data);
                if (data.totalVendors > 0 || data.totalModelFamilies > 0) {
                    setProductTypes(prev => prev.map(pt =>
                        pt.name === selectedProductType.name
                            ? { ...pt, vendorCount: data.totalVendors, modelCount: data.totalModelFamilies }
                            : pt
                    ));
                }
            })
            .catch(e => {
                if (e.name === 'AbortError') return;
                setSelectedProductTypeDetails({ name: selectedProductType.name, vendors: [], totalVendors: 0, totalModelFamilies: 0 });
            })
            .finally(() => setLoadingVendors(false));
        return () => controller.abort();
    }, [selectedProductType]);

    const handleProductTypeClick = (productType: ProductTypeSummary) => {
        setSelectedProductType(productType);
        setVendorSearch("");
        contentRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    };

    const filteredProductTypes = productTypes.filter(pt =>
        pt.name.toLowerCase().includes(productTypeSearch.toLowerCase())
    );

    // Filter vendors within selected product type by global search
    const filteredVendors: VendorData[] = selectedProductTypeDetails
        ? vendorSearch.trim() === ""
            ? selectedProductTypeDetails.vendors
            : selectedProductTypeDetails.vendors.filter(v =>
                v.name.toLowerCase().includes(vendorSearch.toLowerCase()) ||
                v.modelFamilies.some(mf => mf.toLowerCase().includes(vendorSearch.toLowerCase()))
            )
        : [];

    return (
        <div className="flex flex-col h-screen overflow-hidden app-glass-gradient text-foreground font-sans custom-visible-scrollbar-dark">
            {/* Decorative background images */}
            <div className="fixed inset-0 pointer-events-none overflow-hidden z-[0] flex items-center justify-center">
                <img src="/engenie logo.jpeg" alt="" className="w-80 h-80 md:w-[32rem] md:h-[32rem] object-contain opacity-[0.04] select-none translate-y-8 md:translate-y-12" />
            </div>
            <MainHeader showProjectActions={false}>
                <div className="absolute left-1/2 transform -translate-x-1/2 text-center">
                    <h1 className="text-2xl md:text-3xl font-bold text-white inline-flex items-center gap-2">
                        Product Catalog
                    </h1>
                </div>
            </MainHeader>
            <div className="h-24 shrink-0" />

            <div className="flex flex-1 overflow-hidden">
                {loading ? (
                    <div className="flex flex-col items-center justify-center w-full">
                        <Loader2 className="w-12 h-12 animate-spin mb-4 text-primary" />
                        <p className="text-muted-foreground text-lg">Loading catalog...</p>
                    </div>
                ) : error ? (
                    <div className="flex items-center justify-center w-full p-8">
                        <div className="bg-red-50 dark:bg-red-900/20 border-l-4 border-red-500 p-5 rounded-r-xl max-w-lg w-full">
                            <p className="text-red-800 dark:text-red-300 font-semibold">Error loading catalog</p>
                            <p className="mt-1 text-sm text-red-700 dark:text-red-400">{error}</p>
                        </div>
                    </div>
                ) : (
                    <div className="flex flex-1 overflow-hidden">

                        {/* ── LEFT SIDEBAR: PRODUCT TYPES ────────────────────────────────── */}
                        {/* ── LEFT SIDEBAR: PRODUCT TYPES ────────────────────────────────── */}
                        <aside className="w-72 shrink-0 flex flex-col glass-sidebar border-r border-white/10 overflow-hidden z-40">
                            <div className="px-4 pt-5 pb-3 border-b border-white/10">
                                <div className="flex items-center gap-2 mb-3">
                                    <Tag className="w-6 h-6 text-sky-400 shrink-0" />
                                    <h2 className="font-bold text-foreground text-lg">Product Types</h2>
                                    <span className="ml-auto bg-sky-500/10 text-sky-400 text-sm font-semibold rounded-full px-3 py-1">
                                        {productTypes.length}
                                    </span>
                                </div>
                                <div className="relative">
                                    <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500 pointer-events-none" />
                                    <input type="text" placeholder="Search product types..." value={productTypeSearch}
                                        onChange={e => setProductTypeSearch(e.target.value)}
                                        className="w-full pl-7 pr-8 py-2 text-sm rounded-lg bg-[#212121] border border-white/10 text-foreground placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-sky-500/30 hover:scale-[1.02] transition-all duration-200" />
                                    {productTypeSearch && (
                                        <button onClick={() => setProductTypeSearch("")} className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-white">
                                            <X className="w-4 h-4" />
                                        </button>
                                    )}
                                </div>
                            </div>

                            <div className="flex-1 overflow-y-auto custom-visible-scrollbar py-2">
                                {filteredProductTypes.length === 0 ? (
                                    <p className="text-center text-base text-zinc-500 mt-8 px-4">No product types match.</p>
                                ) : filteredProductTypes.map(productType => {
                                    const isSelected = selectedProductType?.name === productType.name;
                                    return (
                                        <button key={productType.name} onClick={() => handleProductTypeClick(productType)}
                                            className={`w-full text-left px-4 py-3 flex items-center gap-3 group transition-all duration-150 border-r-2 ${isSelected ? "bg-sky-500/15 border-sky-500" : "border-transparent hover:bg-white/5"}`}>
                                            <div className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 font-bold text-sm transition-colors ${isSelected ? "bg-sky-500 text-white" : "bg-white/5 border border-white/10 text-zinc-300 group-hover:bg-sky-500/20 group-hover:text-sky-300"}`}>
                                                {productType.name.charAt(0).toUpperCase()}
                                            </div>
                                            <div className="flex-1 min-w-0">
                                                <p className={`text-base font-semibold truncate ${isSelected ? "text-sky-400" : "text-foreground"}`}>{capitalizeFirst(productType.name)}</p>
                                                <p className="text-sm text-muted-foreground">
                                                    {productType.vendorCount} vendors · {productType.modelCount} models
                                                </p>
                                            </div>
                                            {isSelected && <ChevronRight className="w-5 h-5 text-sky-400 shrink-0" />}
                                        </button>
                                    );
                                })}
                            </div>

                            <div className="px-4 py-3 border-t border-white/10 bg-[#171717]/60">
                                <p className="text-sm text-zinc-400 text-center">
                                    <span className="font-semibold text-foreground">{productTypes.reduce((acc, pt) => acc + pt.modelCount, 0).toLocaleString()}</span> total models
                                </p>
                            </div>
                        </aside>

                        {/* ── MAIN CONTENT: VENDORS ─────────────────────────────────── */}
                        <main ref={contentRef} className="flex-1 overflow-y-auto custom-visible-scrollbar">
                            {loadingVendors ? (
                                <div className="flex flex-col items-center justify-center h-full">
                                    <Loader2 className="w-12 h-12 animate-spin mb-4 text-sky-400" />
                                    <p className="text-muted-foreground">Loading vendors...</p>
                                </div>
                            ) : selectedProductType && selectedProductTypeDetails ? (
                                <div className="p-6 md:p-8">
                                    {/* Product Type header */}
                                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
                                        <div className="flex items-center gap-4">
                                            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-sky-500 to-sky-700 flex items-center justify-center text-white font-extrabold text-2xl shadow-lg shadow-sky-500/20 shrink-0">
                                                {selectedProductType.name.charAt(0)}
                                            </div>
                                            <div>
                                                <h1 className="text-3xl md:text-4xl font-extrabold text-foreground leading-tight">{capitalizeFirst(selectedProductType.name)}</h1>
                                                <p className="text-muted-foreground text-base mt-1 flex items-center gap-3">
                                                    <span className="flex items-center gap-1.5"><Building2 className="w-4 h-4" />{selectedProductTypeDetails.totalVendors} vendors</span>
                                                    <span className="flex items-center gap-1.5"><Package className="w-4 h-4" />{selectedProductTypeDetails.totalModelFamilies} models</span>
                                                </p>
                                            </div>
                                        </div>
                                    </div>

                                    <div className="h-px bg-gradient-to-r from-sky-500/30 via-white/10 to-transparent mb-6" />

                                    {/* Global search for vendors/models */}
                                    <div className="relative mb-6">
                                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-zinc-500 pointer-events-none" />
                                        <input type="text" placeholder={`Search vendors and models in ${capitalizeFirst(selectedProductType.name)}...`}
                                            value={vendorSearch} onChange={e => setVendorSearch(e.target.value)}
                                            className="w-full pl-10 pr-10 py-3 text-base rounded-xl bg-[#212121] border border-white/10 text-foreground placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-sky-500/30 shadow-sm backdrop-blur-sm hover:scale-[1.02] transition-all duration-200" />
                                        {vendorSearch && (
                                            <button onClick={() => setVendorSearch("")} className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-white">
                                                <X className="w-5 h-5" />
                                            </button>
                                        )}
                                    </div>

                                    {filteredVendors.length === 0 ? (
                                        <div className="text-center py-16 text-zinc-400 bg-[#171717] rounded-2xl border border-white/10">
                                            {selectedProductTypeDetails.vendors.length === 0 ? (
                                                <>
                                                    <Package className="w-12 h-12 mx-auto mb-4 text-slate-300 dark:text-slate-600" />
                                                    <p className="font-medium text-lg">No vendors or images available yet</p>
                                                    <p className="text-base mt-2">Images will appear here once they are uploaded</p>
                                                </>
                                            ) : (
                                                <>
                                                    <Search className="w-12 h-12 mx-auto mb-4 text-slate-300 dark:text-slate-600" />
                                                    <p className="font-medium text-lg">No results found</p>
                                                    <p className="text-base mt-2">Try adjusting your search</p>
                                                </>
                                            )}
                                        </div>
                                    ) : (
                                        filteredVendors.map((vendor, i) => (
                                            <VendorSection
                                                key={vendor.name}
                                                vendor={vendor}
                                                productType={selectedProductType.name}
                                                viewMode={viewMode}
                                                defaultOpen={i === 0}
                                            />
                                        ))
                                    )}
                                </div>
                            ) : (
                                <div className="flex items-center justify-center h-full flex-col gap-3 text-muted-foreground">
                                    <Database className="w-16 h-16 opacity-30" />
                                    <p className="text-lg font-medium">Select a product type from the sidebar</p>
                                </div>
                            )}
                        </main>
                    </div>
                )}
            </div>
        </div>
    );
}
