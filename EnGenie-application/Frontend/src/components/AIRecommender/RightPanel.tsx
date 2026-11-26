import React, { useEffect, useState, useMemo, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AnalysisResult, RequirementSchema, ValidationResult, AnalysisImageResult, ProductImage, VendorLogo } from "./types";
import { getProductPriceReview, submitFeedback as submitFeedbackApi, BASE_URL } from "./api";
import { Trophy, Loader2, ChevronLeft, ChevronRight, Eye, Send, Download, Table2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import ReactMarkdown from "react-markdown";
import remarkGfm from 'remark-gfm';
import "./ImageComponents.css";

const cleanImageUrl = (url: string): string => {
  if (!url) return "";
  // Check and remove the non-standard x-raw-image:/// scheme
  const prefix = "x-raw-image:///";
  if (url.startsWith(prefix)) {
    return url.substring(prefix.length);
  }
  return url;
};

const getAbsoluteImageUrl = (url: string | undefined | null): string | undefined => {
  if (!url) return undefined;
  const clean = cleanImageUrl(url);
  if (clean.startsWith("http") || clean.startsWith("data:")) return clean;

  const baseUrl = BASE_URL.endsWith("/") ? BASE_URL.slice(0, -1) : BASE_URL;
  const path = clean.startsWith("/") ? clean : `/${clean}`;
  return `${baseUrl}${path}`;
};
// Type that allows images to be either objects or strings
type VendorImage = { fileName: string; url: string; productKey?: string } | string;
type VendorInfo = { name: string; logoUrl: string | null; images: VendorImage[] };

// Image Gallery Component
interface ImageGalleryProps {
  images: ProductImage[];
  isOpen: boolean;
  onClose: () => void;
  productName: string;
}

const ImageGallery: React.FC<ImageGalleryProps> = ({ images, isOpen, onClose, productName }) => {
  if (!isOpen) return null;

  // Helper function for quality badges
  const getQualityBadge = (source: string) => {
    switch (source) {
      case 'google_cse': return '🟢 Official';
      case 'serpapi': return '🟡 Verified';
      case 'serper': return '🟠 General';
      default: return '⚫ Unknown';
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-80 z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-slate-800 max-w-6xl max-h-[90vh] rounded-lg overflow-hidden">
        <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
          <h3 className="text-xl font-bold text-gray-900 dark:text-gray-100">{productName} - All Images</h3>
          <button
            onClick={onClose}
            className="text-2xl font-bold text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
          >
            ×
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 p-4 max-h-[70vh] overflow-y-auto">
          {images.map((image, index) => {
            const finalSrc = getAbsoluteImageUrl(image.url) || "";

            return (
              <div key={index} className="bg-gray-50 dark:bg-gray-700 rounded-lg overflow-hidden">
                <img
                  src={finalSrc}
                  alt={image.title}
                  className="w-full h-48 object-cover"
                />
                <div className="p-3">
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{image.title}</p>
                  <div className="flex items-center justify-between mt-2">
                    <span className="text-xs px-2 py-1 bg-gray-200 dark:bg-gray-600 rounded">{getQualityBadge(image.source)}</span>
                    <span className="text-xs text-gray-500 dark:text-gray-400">{image.domain}</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export type RightPanelProps = {
  productType?: string;
  analysisResult: AnalysisResult;
  validationResult?: ValidationResult;
  requirementSchema?: RequirementSchema;
  isDocked: boolean;
  setIsDocked: React.Dispatch<React.SetStateAction<boolean>>;
  onPricingDataUpdate?: (priceReviewMap: Record<string, PriceReview>) => void;
  userLocation?: string;
  onScroll?: (scrollTop: number) => void;
  initialScrollTop?: number;
  onDownloadWorkflow?: () => void;
};

// PriceReviewResult now includes the 'link' name as nullable
interface PriceReviewResult {
  link: string | null;
  price: string | null;
  reviews: number | null;
  source: string | null;
}

interface PriceReview {
  results: PriceReviewResult[];
}

const RightPanel: React.FC<RightPanelProps> = ({
  productType = "",
  analysisResult,
  validationResult,
  requirementSchema,
  isDocked,
  setIsDocked,
  onPricingDataUpdate,
  userLocation,
  onScroll,
  initialScrollTop = 0,
  onDownloadWorkflow,
}) => {
  const [vendors, setVendors] = useState<VendorInfo[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Restore scroll position
  // Restore scroll position on initial mount and when data loads
  useEffect(() => {
    if (initialScrollTop > 0 && scrollRef.current) {
      requestAnimationFrame(() => {
        if (scrollRef.current) {
          scrollRef.current.scrollTop = initialScrollTop;
        }
      });
    }
  }, [analysisResult, initialScrollTop]);

  // Restore scroll when undocking
  useEffect(() => {
    if (!isDocked && initialScrollTop > 0 && scrollRef.current) {
      requestAnimationFrame(() => {
        if (scrollRef.current) {
          scrollRef.current.scrollTop = initialScrollTop;
        }
      });
    }
  }, [isDocked, initialScrollTop]); // Restore when undocked (component mounts/updates)

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    // Prevent saving "0" scroll position when content is hidden/docked
    if (onScroll && !isDocked) {
      onScroll(e.currentTarget.scrollTop);
    }
  };
  const [hoveredImage, setHoveredImage] = useState<string | null>(null);
  const hideImageTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [priceReviewMap, setPriceReviewMap] = useState<Record<string, PriceReview>>({});
  // Use only embedded analysis images (no external fetching)
  const [analysisImages, setAnalysisImages] = useState<Record<string, AnalysisImageResult>>({});
  const [imageGalleryOpen, setImageGalleryOpen] = useState<{ images: ProductImage[]; productName: string } | null>(null);

  const { toast } = useToast();

  // Keep a stable ref to the callback so the effect below only re-fires
  // when priceReviewMap actually changes, not when the parent re-renders
  // and passes a new function reference.
  const onPricingDataUpdateRef = useRef(onPricingDataUpdate);
  useEffect(() => { onPricingDataUpdateRef.current = onPricingDataUpdate; });

  // Notify parent component when pricing data updates
  useEffect(() => {
    if (onPricingDataUpdateRef.current && Object.keys(priceReviewMap).length > 0) {
      onPricingDataUpdateRef.current(priceReviewMap);
    }
  }, [priceReviewMap]); // intentionally excludes onPricingDataUpdate — use ref above

  type FeedbackType = "positive" | "negative" | null;
  interface FeedbackEntry {
    type: FeedbackType;
    comment: string;
    loading: boolean;
    submitted: boolean;
    response?: string;
  }
  const [feedbackState, setFeedbackState] = useState<Record<string, FeedbackEntry>>({});
  const [feedbackModalOpen, setFeedbackModalOpen] = useState(false);
  const [feedbackModalItem, setFeedbackModalItem] = useState<{ key: string; vendor: string; productName: string; data?: Record<string, unknown> } | null>(null);

  const getProductKey = (vendor: string, productName: string) => `${vendor}-${productName}`;

  // Feedback modal functions
  const openFeedbackModal = (
    key: string,
    vendor: string,
    productName: string,
    initialFeedbackType?: FeedbackType,
    productData?: Record<string, unknown>
  ) => {
    setFeedbackModalItem({ key, vendor, productName, data: productData });
    setFeedbackModalOpen(true);
    if (!feedbackState[key]) {
      setFeedbackState(prev => ({
        ...prev,
        [key]: { type: initialFeedbackType || null, comment: '', loading: false, submitted: false }
      }));
    } else if (initialFeedbackType) {
      setFeedbackState(prev => ({
        ...prev,
        [key]: { ...prev[key], type: initialFeedbackType }
      }));
    }
  };

  const closeFeedbackModal = () => {
    setFeedbackModalOpen(false);
    setTimeout(() => setFeedbackModalItem(null), 200);
  };

  const submitFeedbackForModal = async () => {
    if (!feedbackModalItem) return;
    const { key, vendor, productName, data: productData } = feedbackModalItem;
    const entry = feedbackState[key];
    if (!entry || (!entry.type && !entry.comment.trim())) {
      toast({ title: "No feedback provided", description: "Please select thumbs up/down or add a comment" });
      return;
    }
    setFeedbackState(prev => ({ ...prev, [key]: { ...prev[key], loading: true } }));
    try {
      const projectId = (analysisResult as AnalysisResult & { projectId?: string; project_id?: string })?.projectId || (analysisResult as AnalysisResult & { project_id?: string })?.project_id || undefined;

      // Build complete item metadata from the product data
      const itemMetadata = {
        itemType: 'product',
        itemName: productName,  // Product name
        vendorName: vendor,
        category: productData?.category || '',
        subcategory: productData?.subcategory || '',
        model: productData?.model || '',
        modelFamily: productData?.modelFamily || '',  // Model family for search products
        subModel: productData?.subModel || '',        // Sub model for search products
        userQuery: productData?.userQuery || '',
        recommendationContext: productData?.recommendationContext || {},
        sessionId: projectId || '',
        source: 'search' // From search tab
      };

      const response = await submitFeedbackApi(
        entry.type ?? null,
        entry.comment?.trim() || '',
        projectId,
        itemMetadata
      );

      setFeedbackState(prev => ({
        ...prev,
        [key]: { ...prev[key], loading: false, submitted: true, response }
      }));
      toast({ title: "Feedback submitted!", description: "Thank you for your feedback." });
      setTimeout(() => closeFeedbackModal(), 1500);
    } catch (error: unknown) {
      setFeedbackState(prev => ({ ...prev, [key]: { ...prev[key], loading: false } }));
      const errorMessage = error instanceof Error ? error.message : "Failed to submit feedback";
      toast({ title: "Error", description: errorMessage });
    }
  };

  const handleFeedbackKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submitFeedbackForModal();
    }
  };

  // Function to fetch images for analysis results
  // No external fetching: analysisImages will be prefilled from embedded project data when present

  const setFeedbackType = (key: string, type: FeedbackType) => {
    setFeedbackState((prev) => ({
      ...prev,
      [key]: { type, comment: prev[key]?.comment ?? "", loading: false, submitted: false, response: undefined },
    }));
  };

  const setFeedbackComment = (key: string, comment: string) => {
    setFeedbackState((prev) => ({
      ...prev,
      [key]: { ...prev[key], comment, loading: false, submitted: false },
    }));
  };

  useEffect(() => {
    // Prefer vendor logos/images embedded in the analysisResult (for saved projects)
    if (!analysisResult?.overallRanking?.rankedProducts) return;

    // Use productsToDisplay instead of hardcoded exact match filter
    // This ensures we show images/logos for whichever products are actually displayed (exact or approximate)
    const matchedProducts = productsToDisplay;

    // Try to build vendors list from analysisResult if logos/images were saved with results
    const embeddedVendorsMap: Record<string, VendorInfo> = {};
    matchedProducts.forEach((product) => {
      const name = product.vendor;
      if (!name) return;
      if (!embeddedVendorsMap[name]) embeddedVendorsMap[name] = { name, logoUrl: null, images: [] };

      // Use vendorLogo / vendor_logo if present
      const vlogo = (product as any).vendorLogo || (product as any).vendor_logo;
      if (vlogo && (vlogo.url || vlogo.logo)) {
        const url = vlogo.url || vlogo.logo;
        embeddedVendorsMap[name].logoUrl = cleanImageUrl(url);
      }

      // Use topImage / top_image and allImages / all_images if present
      const topImg = (product as any).topImage || (product as any).top_image;
      if (topImg && topImg.url) {
        embeddedVendorsMap[name].images.push(cleanImageUrl(topImg.url));
      }
      const allImgs = (product as any).allImages || (product as any).all_images;
      if (Array.isArray(allImgs) && allImgs.length > 0) {
        allImgs.forEach((img: any) => {
          if (img && img.url) embeddedVendorsMap[name].images.push(cleanImageUrl(img.url));
        });
      }
    });

    const embeddedVendors = Object.values(embeddedVendorsMap).filter(v => v.logoUrl || (v.images && v.images.length > 0));
    if (embeddedVendors.length > 0) {
      // Use embedded vendor/logo data from analysisResult (e.g., when loading saved project)
      setVendors(embeddedVendors.map(v => ({ name: v.name, logoUrl: v.logoUrl, images: v.images })));
      // Also prefill analysisImages map for products that have top_image in analysisResult
      const preloadedImages: Record<string, AnalysisImageResult> = {};
      matchedProducts.forEach((product) => {
        const key = `${product.vendor}-${product.productName}`;
        const top = (product as any).topImage || (product as any).top_image;
        const all = (product as any).allImages || (product as any).all_images || [];
        const vlogo = (product as any).vendorLogo || (product as any).vendor_logo || null;
        if (top || (all && all.length > 0) || vlogo) {
          preloadedImages[key] = ({
            topImage: top ? { ...top, url: cleanImageUrl(top.url) } : null,
            vendorLogo: vlogo ? { ...vlogo, url: cleanImageUrl(vlogo.url || vlogo.logo) } : null,
            allImages: Array.isArray(all) ? all.map((img: any) => ({ ...img, url: cleanImageUrl(img.url) })) : []
          } as unknown) as AnalysisImageResult;
        }
      });
      setAnalysisImages(preloadedImages);
      return;
    }

    // No embedded vendor media found — clear state from any previous search
    setVendors([]);
    setAnalysisImages({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisResult]); // productsToDisplay is derived from analysisResult; removed vendors.length to allow re-run on new searches

  // Submodel mapping and other external image heuristics removed: we only use embedded media now.

  // External image fetching removed — we rely on embedded analysis images only.



  useEffect(() => {
    if (!analysisResult?.overallRanking?.rankedProducts) return;

    // Use productsToDisplay instead of hardcoded exact match filter
    // This ensures we fetch pricing for whichever products are actually displayed (exact or approximate)
    const matchedProducts = productsToDisplay;

    // Build a priceReviewMap but prefer embedded pricing in saved project data
    const map: Record<string, PriceReview> = {};
    matchedProducts.forEach((product) => {
      const key = `${product.vendor}-${product.productName}`;
      // If product already contains pricing information (saved with project), use it
      if ((product as any).price || (product as any).pricing || (product as any).priceReview) {
        const embedded: PriceReviewResult[] = [];
        if ((product as any).price) {
          embedded.push({ price: (product as any).price, reviews: (product as any).reviews ?? null, source: 'embedded', link: null });
        }
        if ((product as any).pricing && Array.isArray((product as any).pricing.results)) {
          (product as any).pricing.results.forEach((r: any) => embedded.push({ price: r.price ?? null, reviews: r.reviews ?? null, source: r.source ?? null, link: r.link ?? null }));
        }
        if ((product as any).priceReview && Array.isArray((product as any).priceReview.results)) {
          (product as any).priceReview.results.forEach((r: any) => embedded.push({ price: r.price ?? null, reviews: r.reviews ?? null, source: r.source ?? null, link: r.link ?? null }));
        }

        map[key] = { results: embedded };
      } else {
        // Otherwise, attempt to fetch dynamically (fallback)
        map[key] = { results: [] };
        getProductPriceReview(
          product.productName,
          product.vendor,
          (product as any).modelFamily,
          (product as any).subModel,
          productType, // Passed from prop
          userLocation
        )
          .then((data: any) => {
            const normalizedResults: PriceReviewResult[] = (data?.results ?? []).map((r: any) => ({
              price: r.price ?? null,
              reviews: r.reviews ?? null,
              source: r.source ?? null,
              link: r.link ?? null,
            }));
            // sort ascending price
            const sortedResults = normalizedResults.sort((a, b) => {
              const getNumericPrice = (price: string | null) => {
                if (!price) return Infinity;
                const match = price.match(/\d+([.,]\d+)?/);
                return match ? parseFloat(match[0].replace(",", "")) : Infinity;
              };
              return getNumericPrice(a.price) - getNumericPrice(b.price);
            });
            setPriceReviewMap(prev => ({ ...prev, [key]: { results: sortedResults } }));
          })
          .catch(() => {
            // leave empty if fetch fails
          });
      }
    });

    setPriceReviewMap(prev => ({ ...prev, ...map }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisResult]); // productsToDisplay derived from analysisResult; productType/userLocation intentionally excluded

  // Enhanced normalization function for better name matching
  const normalizeText = (name: string): string => {
    if (!name) return "";
    return name
      .toLowerCase()
      .replace(/[\s\-_.+&()[\]{}]/g, "") // Remove spaces, dashes, underscores, dots, plus, ampersand, brackets
      .replace(/[^a-z0-9]/g, "") // Remove any non-alphanumeric characters
      .trim();
  };

  // Create multiple normalized variations of a name for fuzzy matching
  const createNameVariations = (name: string): string[] => {
    const variations = new Set<string>();
    const normalized = normalizeText(name);

    // Add the fully normalized version
    variations.add(normalized);

    // Add version without numbers
    variations.add(normalized.replace(/[0-9]/g, ""));

    // Add version with just letters and first number group
    const firstNumberMatch = name.match(/\d+/);
    if (firstNumberMatch) {
      variations.add(normalizeText(name.split(firstNumberMatch[0])[0] + firstNumberMatch[0]));
    }

    // Add first word only
    const firstWord = name.split(/[\s\-_.]/)[0];
    if (firstWord) {
      variations.add(normalizeText(firstWord));
    }

    return Array.from(variations).filter(v => v.length > 0);
  };

  const normalizeVendorName = (name: string) => normalizeText(name);

  const vendorLogoMap = useMemo(() => {
    const out: { [name: string]: string | null } = {};
    vendors.forEach(({ name, logoUrl }) => {
      out[normalizeVendorName(name)] = logoUrl ?? null;
    });
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vendors]); // normalizeVendorName is a stable function defined in component scope

  // Thresholds for match quality
  // Exact matches: No score threshold - show ALL products where requirementsMatch === true
  // Approximate matches: Minimum score of 50% to ensure reasonable quality
  const APPROXIMATE_THRESHOLD = 50;

  const requirementsMatchMap = useMemo(() => {
    const map = new Map<string, boolean>();
    analysisResult?.vendorAnalysis?.vendorMatches?.forEach((match) => {
      map.set(`${match.vendor}-${match.productName}`, !!match.requirementsMatch);
    });
    return map;
  }, [analysisResult]);

  // Determine which products to display based on fallback logic
  const productsToDisplay = useMemo(() => {
    if (!analysisResult?.overallRanking?.rankedProducts) {
      return [];
    }

    const exactMatches = analysisResult.overallRanking.rankedProducts.filter(
      (product) => {
        const matchStatus = requirementsMatchMap.get(`${product.vendor}-${product.productName}`) ?? product.requirementsMatch;
        return matchStatus === true;
      }
    ).sort((a, b) => (b.overallScore ?? 0) - (a.overallScore ?? 0));

    if (exactMatches.length > 0) return exactMatches;

    return analysisResult.overallRanking.rankedProducts.filter(
      (product) => {
        const matchStatus = requirementsMatchMap.get(`${product.vendor}-${product.productName}`) ?? product.requirementsMatch;
        return matchStatus === false && (product.overallScore ?? 0) >= APPROXIMATE_THRESHOLD;
      }
    ).sort((a, b) => (b.overallScore ?? 0) - (a.overallScore ?? 0));
  }, [analysisResult, requirementsMatchMap]);

  const filteredAnalysisResult = analysisResult
    ? {
      ...analysisResult,
      vendorAnalysis: {
        ...analysisResult.vendorAnalysis,
        vendorMatches: (analysisResult.vendorAnalysis?.vendorMatches ?? []).filter((match) => {
          // Keep only matches that correspond to the products we are displaying
          return productsToDisplay.some(p => p.vendor === match.vendor && p.productName === match.productName);
        }),
      },
      overallRanking: {
        ...analysisResult.overallRanking,
        rankedProducts: productsToDisplay.map((product, index) => ({
          ...product,
          rank: index + 1,
          requirementsMatch: requirementsMatchMap.get(`${product.vendor}-${product.productName}`) ?? product.requirementsMatch,
        })),
      },
    }
    : null;

  const finalAnalysisResult = filteredAnalysisResult;

  // If no matches, render minimal docked panel
  if (!finalAnalysisResult?.vendorAnalysis?.vendorMatches?.length) {
    return (
      <div className="w-full h-full flex flex-col glass-sidebar text-foreground border-l border-border overflow-hidden sticky top-0 right-0 z-20" style={{ minWidth: 0 }}>
        {/* Header space - dock button moved to corner */}
        <div className="flex items-center justify-end py-4 px-3 flex-shrink-0">
          {/* Dock button moved to corner */}
        </div>
        <div style={{ flex: 1 }} />
        <style>{`
          .custom-no-scrollbar::-webkit-scrollbar {
            display: none;
          }
          .custom-no-scrollbar {
            -ms-overflow-style: none;
            scrollbar-width: none;
          }
        `}</style>
      </div>
    );
  }

  const getRankIcon = (rank: number | undefined) => {
    switch (rank) {
      case 1:
        return "🥇";
      case 2:
        return "🥈";
      case 3:
        return "🥉";
      default:
        return rank ? `#${rank}` : "•";
    }
  };

  // Helper function for quality badges
  const getQualityBadge = (source: string) => {
    switch (source) {
      case 'google_cse': return '🟢 Official';
      case 'serpapi': return '🟡 Verified';
      case 'serper': return '🟠 General';
      default: return '⚫ Unknown';
    }
  };

  // Function to open image gallery
  const openImageGallery = (images: ProductImage[], productName: string) => {
    setImageGalleryOpen({ images, productName });
  };

  const renderMarkdownContent = (content: string | string[] | undefined) => {
    if (!content) return null;

    let markdownText = Array.isArray(content) ? content.join("\n\n") : content;

    // Fix issue where LLM squashes items unseparated (e.g., "stability. **Accuracy(0.05%)**")
    markdownText = markdownText.replace(/(\S)\s+(\*\*[a-zA-Z0-9[])/g, '$1\n\n$2');

    // Convert all single linebreaks to double linebreaks to force Markdown paragraph spacing
    markdownText = markdownText.replace(/\r/g, '').replace(/\n+/g, '\n\n');

    return (
      <div
        className="prose prose-sm max-w-none prose-slate dark:prose-invert 
                      prose-headings:text-lg prose-headings:font-bold prose-headings:text-slate-800 dark:prose-headings:text-slate-100 prose-headings:mb-3 prose-headings:mt-4
                      prose-p:text-base prose-p:text-slate-700 dark:prose-p:text-slate-300 prose-p:leading-relaxed prose-p:mb-3
                      prose-strong:text-slate-900 dark:prose-strong:text-slate-100 prose-strong:font-semibold prose-strong:bg-yellow-100 dark:prose-strong:bg-yellow-900/30 prose-strong:px-1 prose-strong:rounded
                      prose-ul:text-base prose-ul:text-slate-700 dark:prose-ul:text-slate-300 prose-ul:mb-3 prose-ul:mt-2
                      prose-li:text-slate-700 dark:prose-li:text-slate-300 prose-li:leading-relaxed prose-li:mb-2 prose-li:pl-1
                      prose-h1:text-xl prose-h1:font-bold prose-h1:text-[#0F6CBD] dark:prose-h1:text-sky-300 prose-h1:mb-4 prose-h1:mt-4 prose-h1:border-b prose-h1:border-[#5FB3E6]/30 prose-h1:pb-2
                      prose-h2:text-lg prose-h2:font-bold prose-h2:text-[#0F6CBD] dark:prose-h2:text-sky-400 prose-h2:mb-3 prose-h2:mt-4
                      prose-h3:text-base prose-h3:font-semibold prose-h3:text-[#0F6CBD] dark:prose-h3:text-sky-500 prose-h3:mb-2 prose-h3:mt-3
                      prose-h4:text-sm prose-h4:font-semibold prose-h4:text-slate-600 dark:prose-h4:text-slate-400 prose-h4:mb-2 prose-h4:mt-2
                      prose-code:text-pink-600 dark:prose-code:text-pink-400 prose-code:bg-pink-50 dark:prose-code:bg-pink-900/30 prose-code:px-1 prose-code:rounded prose-code:font-mono prose-code:text-sm
                      prose-blockquote:border-l-4 prose-blockquote:border-[#5FB3E6] prose-blockquote:bg-[#F5FAFC] dark:prose-blockquote:bg-sky-900/20 prose-blockquote:pl-4 prose-blockquote:py-2 prose-blockquote:italic
                      [&_ul]:ml-2 [&_li]:ml-0 [&_p]:select-text [&_li]:select-text [&_strong]:select-text [&_code]:select-text
                      [&_ul>li]:marker:text-[#5FB3E6] [&_ol>li]:marker:text-[#5FB3E6] [&_ol>li]:marker:font-semibold
                      [&_em]:text-slate-600 dark:[&_em]:text-slate-400 [&_em]:italic [&_em]:font-medium"
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdownText}</ReactMarkdown>
      </div>
    );
  };

  const CircularProgressBarSVG = ({ score }: { score: number }) => {
    const safeScore = Math.max(0, Math.min(100, Number.isFinite(score) ? score : 0));
    const radius = 20;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference * (1 - safeScore / 100);
    const strokeColor = safeScore >= 80 ? "#16a34a" : safeScore >= 60 ? "#f59e0b" : "#ef4444";
    return (
      <svg className="w-full h-full text-foreground" viewBox="0 0 44 44">
        <circle cx="22" cy="22" r={radius} stroke="#e5e7eb" strokeWidth="4" fill="transparent" />
        <circle
          cx="22"
          cy="22"
          r={radius}
          stroke={strokeColor}
          strokeWidth="4"
          strokeLinecap="round"
          fill="transparent"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform="rotate(-90 22 22)"
        />
        <text x="22" y="22" dominantBaseline="middle" textAnchor="middle" fontSize="10" fontWeight="bold" fill="currentColor">
          {`${safeScore}%`}
        </text>
      </svg>
    );
  };

  // Helper to return border color classes for containers based on score
  const getBorderColor = (overallScore: number | undefined) => {
    return "border-[#45A4DE]";
  };

  const { vendorAnalysis, overallRanking, comparisonTable } = finalAnalysisResult!;
  const vendorsGrouped = (overallRanking.rankedProducts || []).reduce((acc: { [vendor: string]: typeof overallRanking.rankedProducts }, current) => {
    if (!acc[current.vendor]) acc[current.vendor] = [];
    acc[current.vendor].push(current);
    return acc;
  }, {});
  const vendorNames = Object.keys(vendorsGrouped);
  const hasComparisonTable = !!comparisonTable && comparisonTable.specKeys.length > 0 && comparisonTable.rows.length > 0;

  const RenderVendorLogo: React.FC<{ vendorName: string; size?: number }> = ({ vendorName, size = 22 }) => {
    const [imgError, setImgError] = React.useState(false);
    const normalizedVendorName = normalizeVendorName(vendorName);
    const logoUrl = vendorLogoMap[normalizedVendorName];
    const initial = (
      <span
        style={{
          width: size,
          height: size,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: Math.round(size * 0.5),
          fontWeight: "bold",
          borderRadius: 4,
          flexShrink: 0,
        }}
      >
        {vendorName.charAt(0).toUpperCase()}
      </span>
    );
    if (!logoUrl || imgError) return initial;
    const safeUrl = getAbsoluteImageUrl(logoUrl);
    return (
      <img
        src={safeUrl}
        alt={`${vendorName} logo`}
        style={{
          width: size,
          height: size,
          objectFit: "contain",
          borderRadius: 4,
          marginRight: 6,
        }}
        onError={() => setImgError(true)}
      />
    );
  };

  const getPriceReview = (vendor: string, productName: string): PriceReview => {
    const key = `${vendor}-${productName}`;
    return priceReviewMap[key] || { results: [] };
  };

  return (
    <div className="w-full h-full flex flex-col glass-sidebar text-foreground border-l border-border sticky top-0 right-0 z-20" style={{ minWidth: 0, position: "relative" }}>


      {/* Header space - toolbar actions */}
      {!isDocked && (
        <div className="flex items-center justify-between py-3 px-4 border-b border-border/40 flex-shrink-0">
          <span className="text-xs font-semibold text-foreground flex items-center gap-1.5">
            <Trophy className="h-3.5 w-3.5 text-amber-500" />
            <span>Vendor Recommendations</span>
          </span>
          {onDownloadWorkflow && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onDownloadWorkflow}
              className="h-8 px-2.5 rounded-lg border-sky-300 dark:border-sky-700/60 bg-sky-50/80 dark:bg-sky-950/40 text-sky-700 dark:text-sky-300 hover:bg-sky-100 hover:text-sky-800 transition-all flex items-center gap-1.5 shadow-xs cursor-pointer font-medium text-xs"
              title="Download Search Workflow Report (PDF / CSV / JSON)"
            >
              <Download className="h-3.5 w-3.5 text-sky-600 dark:text-sky-400" />
              <span>Download Report</span>
            </Button>
          )}
        </div>
      )}


      {/* Docked view: show compact summary/icon */}
      {isDocked ? (
        <div className="flex flex-col items-center justify-center flex-1 py-8">
          <Trophy className="w-8 h-8 text-muted-foreground mb-2" />
          <span className="text-xs text-muted-foreground">Results</span>
        </div>
      ) : (
        <ScrollArea
          viewportRef={scrollRef}
          onViewportScroll={handleScroll}
          className="flex-1 overflow-auto custom-no-scrollbar min-w-0"
        >
          <div className="p-4 space-y-4 min-w-0 flex flex-col">
            <Tabs defaultValue="ranking" className="w-full min-w-0">
              <ScrollArea className="w-full whitespace-nowrap min-w-0">
                <TabsList className="flex w-full p-1 rounded-xl bg-muted/30">
                  <TabsTrigger value="ranking" className="flex-shrink-0 px-4 py-2 rounded-lg transition-all bg-transparent data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:scale-125 hover:bg-transparent whitespace-nowrap flex items-center justify-center">
                    <Trophy className="h-5 w-5 text-slate-700 dark:text-slate-200" />
                  </TabsTrigger>
                  {hasComparisonTable && (
                    <TabsTrigger
                      value="compare"
                      className="flex-shrink-0 px-4 py-2 rounded-lg transition-all bg-transparent data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:scale-125 hover:bg-transparent whitespace-nowrap flex items-center justify-center"
                      title="Compare"
                      aria-label="Compare"
                    >
                      <Table2 className="h-5 w-5 text-slate-700 dark:text-slate-200" />
                    </TabsTrigger>
                  )}
                  {vendorNames.map((vendorName) => (
                    <TabsTrigger
                      key={vendorName}
                      value={vendorName}
                      className="flex-shrink-0 px-4 py-2 rounded-lg transition-all bg-transparent data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:scale-125 hover:bg-transparent whitespace-nowrap flex items-center gap-1 justify-center"
                      title={vendorName}
                      aria-label={vendorName}
                      style={{ minWidth: 30, minHeight: 30 }}
                    >
                      <RenderVendorLogo vendorName={vendorName} size={40} />
                      <span
                        style={{
                          position: "absolute",
                          width: 1,
                          height: 1,
                          padding: 0,
                          overflow: "hidden",
                          clip: "rect(0, 0, 0, 0)",
                          whiteSpace: "nowrap",
                          border: 0,
                        }}
                        aria-hidden="true"
                      >
                        {vendorName}
                      </span>
                    </TabsTrigger>
                  ))}
                </TabsList>
                <ScrollBar orientation="horizontal" className="h-1.5" />
              </ScrollArea>

              {/* Search Tab */}
              <TabsContent value="ranking" className="mt-4 min-w-0">
                <Card className="bg-gradient-card shadow-card rounded-lg min-w-0 flex flex-col">
                  <CardHeader className="pb-3 min-w-0">
                    <CardTitle className="text-sm font-semibold flex items-center min-w-0 flex-wrap"></CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3 min-w-0">
                    {overallRanking.rankedProducts.map((product, index) => {
                      const key = `${product.vendor}-${product.productName}`;
                      const imageData = analysisImages[key];
                      const isLoadingImage = false;
                      const rawProductImgUrl = imageData?.topImage?.url || (product as any).topImage?.url || (product as any).top_image?.url || product.imageUrl;
                      const productImgUrl = getAbsoluteImageUrl(rawProductImgUrl);
                      const priceReviews = getPriceReview(product.vendor, product.productName);
                      const fbKey = getProductKey(product.vendor, product.productName);
                      const fb = feedbackState[fbKey] ?? { type: null, comment: "", loading: false, submitted: false };

                      const overallScore = product.overallScore ?? 0;

                      return (
                        <div
                          key={`${product.vendor}-${product.productName}-${index}`}
                          className={`bg-white/60 dark:bg-slate-900/60 backdrop-blur-md rounded-2xl p-6 shadow-xl border-2 ${getBorderColor(overallScore)} w-full max-w-full overflow-hidden break-words hover:shadow-2xl transition-all duration-300 transform hover:-translate-y-1`}
                          style={{ position: "relative" }}
                        >
                          <div className="flex items-center justify-between flex-wrap min-w-0 gap-2">
                            <div className="flex flex-col flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                {/* Product image before product name */}
                                {isLoadingImage ? (
                                  <div className="w-10 h-10 bg-gray-200 dark:bg-gray-700 rounded animate-pulse flex items-center justify-center flex-shrink-0">
                                    <span className="text-xs text-gray-500">...</span>
                                  </div>
                                ) : productImgUrl ? (
                                  <div className="relative flex-shrink-0">
                                    <img
                                      src={productImgUrl}
                                      alt={`${product.productName} thumbnail`}
                                      onMouseEnter={() => {
                                        if (hideImageTimeout.current) clearTimeout(hideImageTimeout.current);
                                        setHoveredImage(productImgUrl);
                                      }}
                                      onMouseLeave={() => {
                                        hideImageTimeout.current = setTimeout(() => setHoveredImage(null), 150);
                                      }}
                                      className="w-10 h-10 rounded object-contain cursor-pointer hover:scale-110 transition-transform"
                                    />
                                    {imageData?.topImage?.source && (
                                      <div className="absolute -top-1 -right-1 text-xs">
                                        {getQualityBadge(imageData.topImage.source).charAt(0)}
                                      </div>
                                    )}
                                  </div>
                                ) : null}
                                <h2 className="font-bold truncate select-text text-xl text-slate-900 dark:text-slate-100">{product.productName}</h2>
                              </div>
                              <div className="flex items-center gap-2 mt-1">
                                <p className="text-base font-medium text-slate-600 dark:text-slate-400 truncate select-text">{product.vendor}</p>
                              </div>
                            </div>
                            <div className="w-12 h-12 flex items-center justify-center relative">
                              <CircularProgressBarSVG score={overallScore} />
                            </div>
                          </div>

                          <div className="space-y-6 mt-3">
                            <div className="p-4 rounded-xl bg-gradient-to-r from-green-50 to-emerald-50 dark:from-green-900/20 dark:to-emerald-900/20 border border-green-200 dark:border-green-700/50 shadow-sm transition-transform duration-300 hover:scale-[1.01]">
                              <div className="flex items-center gap-2 mb-3">
                                <span className="text-lg">✨</span>
                                <p className="text-lg font-bold text-green-800 dark:text-green-300 select-text">Highlights</p>
                              </div>
                              {renderMarkdownContent(product.keyStrengths)}
                            </div>

                            {product.concerns && (
                              <div className="p-4 rounded-xl bg-gradient-to-r from-amber-50 to-orange-50 dark:from-amber-900/20 dark:to-orange-900/20 border border-amber-200 dark:border-amber-700/50 shadow-sm transition-transform duration-300 hover:scale-[1.01]">
                                <div className="flex items-center gap-2 mb-3">
                                  <span className="text-lg">⚠️</span>
                                  <p className="text-lg font-bold text-amber-800 dark:text-amber-300 select-text">Limitations</p>
                                </div>
                                {renderMarkdownContent(product.concerns)}
                              </div>
                            )}

                            {priceReviews.results.length > 0 && (
                              <div className="p-4 rounded-xl bg-gradient-to-r from-[#F5FAFC] to-[#EAF6FB] dark:from-sky-900/20 dark:to-sky-800/20 border border-[#5FB3E6]/30 dark:border-sky-700/50 shadow-sm transition-transform duration-300 hover:scale-[1.01]">
                                <div className="flex items-center gap-2 mb-3">
                                  <span className="text-lg">💰</span>
                                  <p className="text-lg font-bold text-[#0F6CBD] dark:text-sky-300 select-text">Pricing Information</p>

                                </div>
                                <div className="space-y-3">
                                  {priceReviews.results
                                    .filter((result) => result.price)
                                    .slice(0, 10)
                                    .map((result, idx) => (
                                      <div key={idx} className="flex items-center justify-between p-3 bg-white dark:bg-slate-800 rounded-lg border border-[#5FB3E6]/20 dark:border-sky-800/50 transition-transform duration-300 hover:scale-[1.02]">
                                        <div className="flex flex-col">
                                          <span className="text-xl font-bold text-[#0F6CBD] dark:text-sky-400">{result.price}</span>
                                          {result.source && <span className="text-sm text-slate-600 dark:text-slate-400">Available on {result.source}</span>}
                                        </div>
                                        {result.link && (
                                          <a href={result.link} target="_blank" rel="noopener noreferrer" className="p-2 text-[#0F6CBD] hover:text-[#084275] dark:text-sky-400 dark:hover:text-sky-200 transition-all duration-300 hover:scale-110 flex items-center justify-center">
                                            <Eye className="h-5 w-5" />
                                          </a>
                                        )}
                                      </div>
                                    ))}
                                </div>
                              </div>
                            )}

                            {/* Feedback Icons */}
                            <div className="-mt-2 flex justify-end gap-3">
                              <button
                                onClick={() => openFeedbackModal(fbKey, product.vendor, product.productName, 'positive', product)}
                                className="transition-transform duration-300 hover:scale-125"
                              >
                                <img
                                  src="/icon-thumbs-3d.png"
                                  alt="Thumbs Up"
                                  className="h-12 w-12 object-contain"
                                />
                              </button>
                              <button
                                onClick={() => openFeedbackModal(fbKey, product.vendor, product.productName, 'negative', product)}
                                className="transition-transform duration-300 hover:scale-125"
                              >
                                <img
                                  src="/icon-thumbsdown-3d.png"
                                  alt="Thumbs Down"
                                  className="h-12 w-12 object-contain"
                                />
                              </button>
                            </div>
                          </div>

                          {index < overallRanking.rankedProducts.length - 1 && <Separator className="my-3" />}
                        </div>
                      );
                    })}
                  </CardContent>
                </Card>
              </TabsContent>

              {/* Compare Tab */}
              {hasComparisonTable && (
                <TabsContent value="compare" className="mt-4 min-w-0">
                  <Card className="bg-gradient-card shadow-card rounded-lg min-w-0 flex flex-col">
                    <CardHeader className="pb-3 min-w-0">
                      <CardTitle className="text-sm font-semibold flex items-center gap-2 min-w-0 flex-wrap">
                        <Table2 className="h-4 w-4 text-slate-700 dark:text-slate-200" />
                        <span>Spec Comparison</span>
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="min-w-0">
                      <div className="overflow-x-auto rounded-xl border border-border/60">
                        <table className="min-w-full text-sm border-collapse">
                          <thead>
                            <tr>
                              <th className="sticky left-0 z-10 bg-muted/60 backdrop-blur-sm text-left font-semibold text-xs uppercase tracking-wide text-slate-600 dark:text-slate-300 px-3 py-2 border-b border-border/60 whitespace-nowrap">
                                Spec
                              </th>
                              {comparisonTable!.rows.map((row, idx) => (
                                <th
                                  key={`${row.vendor}-${row.productName}-${idx}`}
                                  className="text-left font-semibold text-xs px-3 py-2 border-b border-border/60 whitespace-nowrap min-w-[140px]"
                                >
                                  <div className="flex items-center gap-1.5">
                                    <RenderVendorLogo vendorName={row.vendor} size={18} />
                                    <div className="flex flex-col leading-tight">
                                      <span className="text-slate-900 dark:text-slate-100">{row.productName}</span>
                                      <span className="text-[10px] font-normal text-slate-500 dark:text-slate-400">{row.vendor}</span>
                                    </div>
                                  </div>
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {comparisonTable!.specKeys.map((specKey, rowIdx) => (
                              <tr key={specKey} className={rowIdx % 2 === 0 ? "bg-transparent" : "bg-muted/20"}>
                                <td className="sticky left-0 z-10 bg-inherit backdrop-blur-sm px-3 py-2 border-b border-border/40 font-medium text-slate-700 dark:text-slate-300 whitespace-nowrap">
                                  {specKey.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/^./, (c) => c.toUpperCase())}
                                </td>
                                {comparisonTable!.rows.map((row, colIdx) => {
                                  const value = row.values?.[specKey];
                                  return (
                                    <td
                                      key={`${specKey}-${row.vendor}-${row.productName}-${colIdx}`}
                                      className="px-3 py-2 border-b border-border/40 text-slate-800 dark:text-slate-200 whitespace-nowrap"
                                    >
                                      {value ?? <span className="text-slate-400 dark:text-slate-600">—</span>}
                                    </td>
                                  );
                                })}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </CardContent>
                  </Card>
                </TabsContent>
              )}

              {/* Vendor Specific Tabs */}
              {vendorNames.map((vendorName) => (
                <TabsContent key={vendorName} value={vendorName} className="mt-4 min-w-0">
                  <Card className="bg-gradient-card shadow-card rounded-lg min-w-0 flex flex-col">
                    <CardHeader className="pb-3 min-w-0">

                    </CardHeader>
                    <CardContent className="space-y-4 min-w-0">
                      {vendorsGrouped[vendorName]
                        .sort((a, b) => (b.overallScore ?? 0) - (a.overallScore ?? 0))
                        .map((productMatch, idx) => {
                          // Get product-specific image from analysis images
                          const key = `${productMatch.vendor}-${productMatch.productName}`;
                          const imageData = analysisImages[key];
                          const rawProductImgUrl = imageData?.topImage?.url || (productMatch as any).topImage?.url || (productMatch as any).top_image?.url || productMatch.imageUrl;
                          const productImgUrl = getAbsoluteImageUrl(rawProductImgUrl);
                          const priceReviews = getPriceReview(productMatch.vendor, productMatch.productName);
                          const overallScore = productMatch.overallScore ?? 0;

                          return (
                            <div
                              key={`${productMatch.vendor}-${productMatch.productName}-${idx}`}
                              className={`bg-white/60 dark:bg-slate-900/60 backdrop-blur-md rounded-2xl p-6 shadow-xl border-2 ${getBorderColor(
                                overallScore
                              )} w-full max-w-full overflow-hidden break-words hover:shadow-2xl transition-all duration-300 transform hover:-translate-y-1`}
                            >
                              <div className="flex items-center justify-between flex-wrap min-w-0 gap-2">
                                {/* Product image (not vendor logo) */}
                                {productImgUrl ? (
                                  <img
                                    src={productImgUrl}
                                    alt={`${productMatch.productName} thumbnail`}
                                    onMouseEnter={() => setHoveredImage(productImgUrl)}
                                    onMouseLeave={() => setHoveredImage(null)}
                                    style={{
                                      width: 30,
                                      height: 30,
                                      borderRadius: 6,
                                      objectFit: "contain",
                                      cursor: "pointer",
                                      flexShrink: 0,
                                    }}
                                  />
                                ) : (
                                  <span className="flex-shrink-0 text-lg select-none">{productMatch.productName?.charAt(0) ?? "•"}</span>
                                )}
                                <div className="flex flex-col flex-1 min-w-0">
                                  <h2 className="font-bold truncate select-text text-xl text-slate-900 dark:text-slate-100 mb-1">{productMatch.productName}</h2>
                                  <div className="flex items-center gap-2"></div>
                                </div>
                                <div className="w-12 h-12 flex items-center justify-center relative">
                                  <CircularProgressBarSVG score={overallScore} />
                                </div>
                              </div>

                              <div className="space-y-3 mt-3">
                                <div className="p-4 rounded-xl bg-gradient-to-r from-green-50 to-emerald-50 dark:from-green-900/20 dark:to-emerald-900/20 border border-green-200 dark:border-green-700/50 shadow-sm transition-transform duration-300 hover:scale-[1.01] mb-6">
                                  <div className="flex items-center gap-2 mb-3">
                                    <span className="text-lg">✨</span>
                                    <p className="text-lg font-bold text-green-800 dark:text-green-300 select-text">Highlights</p>
                                  </div>
                                  {renderMarkdownContent(productMatch.keyStrengths)}
                                </div>

                                {productMatch.concerns && (
                                  <div className="p-4 rounded-xl bg-gradient-to-r from-amber-50 to-orange-50 dark:from-amber-900/20 dark:to-orange-900/20 border border-amber-200 dark:border-amber-700/50 shadow-sm transition-transform duration-300 hover:scale-[1.01] mb-6">
                                    <div className="flex items-center gap-2 mb-3">
                                      <span className="text-lg">⚠️</span>
                                      <p className="text-lg font-bold text-amber-800 dark:text-amber-300 select-text">Limitations</p>
                                    </div>
                                    {renderMarkdownContent(productMatch.concerns)}
                                  </div>
                                )}

                                {priceReviews.results.length > 0 && (
                                  <div className="p-4 rounded-xl bg-gradient-to-r from-[#F5FAFC] to-[#EAF6FB] dark:from-sky-900/20 dark:to-sky-800/20 border border-[#5FB3E6]/30 dark:border-sky-700/50 shadow-sm transition-transform duration-300 hover:scale-[1.01] mb-6">
                                    <div className="flex items-center gap-2 mb-3">
                                      <span className="text-lg">💰</span>
                                      <p className="text-lg font-bold text-[#0F6CBD] dark:text-sky-300 select-text">Pricing Information</p>

                                    </div>
                                    <div className="space-y-3">
                                      {priceReviews.results
                                        .filter((result) => result.price)
                                        .slice(0, 10)
                                        .map((result, idx) => (
                                          <div key={idx} className="flex items-center justify-between p-3 bg-white dark:bg-slate-800 rounded-lg border border-[#5FB3E6]/20 dark:border-sky-800/50 transition-transform duration-300 hover:scale-[1.02]">
                                            <div className="flex flex-col">
                                              <span className="text-xl font-bold text-[#0F6CBD] dark:text-sky-400">{result.price}</span>
                                              {result.source && <span className="text-sm text-slate-600 dark:text-slate-400">Available on {result.source}</span>}
                                            </div>
                                            {result.link && (
                                              <a href={result.link} target="_blank" rel="noopener noreferrer" className="p-2 text-[#0F6CBD] hover:text-[#084275] dark:text-sky-400 dark:hover:text-sky-200 transition-all duration-300 hover:scale-110 flex items-center justify-center" title="View Deal">
                                                <Eye className="h-5 w-5" />
                                              </a>
                                            )}
                                          </div>
                                        ))}
                                    </div>
                                  </div>
                                )}
                              </div>

                              {idx < vendorsGrouped[vendorName].length - 1 && <Separator className="my-3" />}
                            </div>
                          );
                        })}
                    </CardContent>
                  </Card>
                </TabsContent>
              ))}
            </Tabs>
          </div>
        </ScrollArea>
      )}

      {hoveredImage && (
        <div
          onMouseEnter={() => {
            if (hideImageTimeout.current) clearTimeout(hideImageTimeout.current);
          }}
          onMouseLeave={() => setHoveredImage(null)}
          style={{
            position: "fixed",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -50%)",
            background: "rgba(255, 255, 255, 0.98)",
            padding: 24,
            borderRadius: 16,
            boxShadow: "0 20px 60px rgba(0,0,0,0.4)",
            zIndex: 9999,
            maxWidth: "220px",
            maxHeight: "220px",
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            border: "2px solid rgba(0,0,0,0.1)",
          }}
          className="dark:bg-slate-800/98 dark:border-slate-600"
        >
          <img
            src={hoveredImage ? (hoveredImage.startsWith("/") ? `${BASE_URL}${hoveredImage}` : hoveredImage) : undefined}
            alt="Product preview"
            style={{
              maxWidth: "180px",
              maxHeight: "180px",
              objectFit: "contain",
              borderRadius: 12,
            }}
          />
        </div>
      )}

      {/* Image Gallery Modal */}
      {imageGalleryOpen && (
        <ImageGallery
          images={imageGalleryOpen.images}
          isOpen={true}
          onClose={() => setImageGalleryOpen(null)}
          productName={imageGalleryOpen.productName}
        />
      )}

      {/* Feedback Modal - Matching OTP Popup Styling */}
      {feedbackModalOpen && feedbackModalItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6 animate-in fade-in duration-200">
          <div className="max-w-sm w-full relative animate-in zoom-in-95 duration-300 acrylic-glass-pill p-6" style={{ backdropFilter: 'blur(80px)', backgroundColor: 'rgba(255, 255, 255, 0.65)' }}>
            {/* Close Button */}
            <button
              onClick={closeFeedbackModal}
              className="absolute top-5 right-8 text-muted-foreground hover:text-foreground hover:scale-125 transition-all duration-200"
              title="Close"
            >
              <span className="text-lg">✕</span>
            </button>

            {/* Header */}
            <div className="text-center mb-4">
              <div className="flex items-center justify-center gap-2 mb-1">
                <span className="text-3xl opacity-80">💬</span>
                <h2 className="text-xl font-bold">Feedback</h2>
              </div>
              <p className="text-muted-foreground text-xs">
                Help us improve by sharing your thoughts on
                <br />
                <span className="font-semibold">
                  {feedbackModalItem.productName}
                </span>
              </p>
            </div>

            {(() => {
              const fb = feedbackState[feedbackModalItem.key] || { type: null, comment: '', loading: false, submitted: false };

              return (
                <div className="space-y-3">
                  {/* Thumbs Buttons */}
                  <div className="flex items-center justify-center gap-6">
                    <button
                      onClick={() => setFeedbackType(feedbackModalItem.key, "positive")}
                      className="transition-all duration-300 hover:scale-110 cursor-pointer p-2 rounded-full"
                    >
                      <img
                        src="/icon-thumbs-3d.png"
                        alt="Thumbs Up"
                        className={`h-16 w-16 object-contain transition-all duration-300 ${
                          fb.type === "positive"
                            ? "brightness-100 saturate-150 drop-shadow-lg scale-110"
                            : "brightness-75 opacity-60"
                        }`}
                      />
                    </button>
                    <button
                      onClick={() => setFeedbackType(feedbackModalItem.key, "negative")}
                      className="transition-all duration-300 hover:scale-110 cursor-pointer p-2 rounded-full"
                    >
                      <img
                        src="/icon-thumbsdown-3d.png"
                        alt="Thumbs Down"
                        className={`h-16 w-16 object-contain transition-all duration-300 ${
                          fb.type === "negative"
                            ? "brightness-100 saturate-150 drop-shadow-lg scale-110"
                            : "brightness-75 opacity-60"
                        }`}
                      />
                    </button>
                  </div>

                  {/* Success Message */}
                  {fb.submitted ? (
                    <p className="text-xs text-green-500 text-center flex items-center justify-center gap-1 py-2">
                      <span className="text-base">✓</span>
                      {fb.response || "Thanks for your feedback!"}
                    </p>
                  ) : (
                    <>
                      {/* Comment Textarea */}
                      <div className="space-y-2">
                        <label className="text-sm font-medium text-muted-foreground">
                          Additional Comments (Optional)
                        </label>
                        <Textarea
                          value={fb.comment}
                          onChange={(e) => setFeedbackComment(feedbackModalItem.key, e.target.value)}
                          onKeyDown={handleFeedbackKeyDown}
                          className="form-glass-input rounded-xl min-h-[100px] transition-all duration-300 focus:ring-2 focus:ring-[#5FB3E6] resize-none"
                          placeholder="Tell us what you think..."
                          disabled={fb.loading}
                        />
                      </div>

                      {/* Action Buttons */}
                      <div className="flex gap-2 pt-1">
                        <Button
                          type="button"
                          onClick={closeFeedbackModal}
                          variant="ghost"
                          disabled={fb.loading}
                          className="flex-1 rounded-xl py-2.5 text-muted-foreground hover:text-foreground"
                        >
                          Cancel
                        </Button>
                        <Button
                          type="button"
                          onClick={submitFeedbackForModal}
                          disabled={fb.loading || (!fb.type && !fb.comment.trim())}
                          className={`flex-1 rounded-xl py-2.5 font-semibold transition-opacity duration-300 hover:brightness-100 hover:saturate-100 ${fb.loading || (!fb.type && !fb.comment.trim())
                            ? 'btn-glass-primary opacity-50 cursor-not-allowed'
                            : 'btn-glass-primary'
                          }`}
                        >
                          {fb.loading ? (
                            <>
                              <Loader2 className="h-4 w-4 animate-spin mr-2" />
                              Submitting...
                            </>
                          ) : (
                            "Submit Feedback"
                          )}
                        </Button>
                      </div>
                    </>
                  )}
                </div>
              );
            })()}
          </div>
        </div>
      )}

      <style>{`
        .custom-no-scrollbar::-webkit-scrollbar {
          display: none;
        }
        .custom-no-scrollbar {
          -ms-overflow-style: none;
          scrollbar-width: none;
        }
      `}</style>
    </div>
  );
};

export default RightPanel;