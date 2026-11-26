import React, { useState, useEffect, useRef } from "react";
import { Bot } from "lucide-react";
import { RequirementSchema, ValidationResult } from "./types";
import { getFieldDescriptionsBatch } from "./api";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// Helper functions
function capitalizeFirstLetter(str?: string): string {
  if (!str) return "";
  return str.charAt(0).toUpperCase() + str.slice(1);
}

function prettify(raw: string): string {
  if (!raw) return "";
  return raw
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[-_]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .split(" ")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function getNestedValue(obj: Record<string, unknown> | null | undefined, path: string): unknown {
  if (!obj) return undefined;

  // First check if the path exists as a direct key (flat structure with dot-notation keys)
  if (path in obj) {
    const value = obj[path];
    // Debug log for materials field
    if (path.includes('materials') || path.includes('measurementPrinciple')) {
      console.log(`[SIDEBAR getNestedValue] Flat key found: "${path}" = "${value}"`);
    }
    return value;
  }

  // Otherwise, try nested traversal
  const result = path.split(".").reduce<unknown>((acc, k) => (acc && typeof acc === 'object' ? (acc as Record<string, unknown>)[k] : undefined), obj);
  if (path.includes('materials') || path.includes('measurementPrinciple')) {
    console.log(`[SIDEBAR getNestedValue] Nested traversal for "${path}" = "${result}"`);
  }
  return result;
}

function getAllLeafKeys(obj: Record<string, unknown> | null | undefined, parentKey = ""): string[] {
  if (!obj) return [];
  return Object.entries(obj).flatMap(([key, value]) =>
    value && typeof value === "object" && !Array.isArray(value)
      ? getAllLeafKeys(value as Record<string, unknown>, parentKey ? `${parentKey}.${key}` : key)
      : [parentKey ? `${parentKey}.${key}` : key]
  );
}

// Field data type for rendering
interface FieldData {
  fullKey: string;
  fieldName: string;
  hierarchicalLabel: string;
  displayValue: string;
  isFilled: boolean;
  fieldDescriptions: Record<string, string>;
}

// Helper function to render all fields in a flat structure within one container
function renderFlatFieldsList(
  obj: Record<string, unknown>,
  collectedData: Record<string, unknown>,
  fieldDescriptions: Record<string, string>,
  parentKey = ""
): JSX.Element[] {
  const fieldsByCategory: Record<string, FieldData[]> = {};

  function traverseAndCollect(currentObj: Record<string, unknown>, currentParentKey = "", hierarchyPath: string[] = []) {
    Object.entries(currentObj).forEach(([key, value]) => {
      const fullKey = currentParentKey ? `${currentParentKey}.${key}` : key;
      const newHierarchyPath = [...hierarchyPath, prettify(key)];

      if (value !== null && typeof value === "object" && !Array.isArray(value)) {
        // Recursively traverse nested objects, building the hierarchy path
        traverseAndCollect(value, fullKey, newHierarchyPath);
      } else {
        // This is a leaf field, group it by category
        const valueRaw = getNestedValue(collectedData, fullKey);
        let displayValue = Array.isArray(valueRaw) ? valueRaw.join(", ") : String(valueRaw ?? "");
        let isFilled = valueRaw !== undefined && valueRaw !== "" && valueRaw !== null;

        // Values come from chat extraction / mappedRequirements sync only (no DB template fallback).

        const fieldName = prettify(key);
        const hierarchicalLabel = newHierarchyPath.length > 1
          ? `${newHierarchyPath.slice(0, -1).join(" > ")} > ${fieldName}`
          : fieldName;
        const categoryPath = newHierarchyPath.slice(0, -1).join(" ");

        // Group fields by category
        const category = categoryPath || "General";
        if (!fieldsByCategory[category]) {
          fieldsByCategory[category] = [];
        }

        fieldsByCategory[category].push({
          fullKey,
          fieldName,
          hierarchicalLabel,
          displayValue,
          isFilled,
          fieldDescriptions
        });
      }
    });
  }

  traverseAndCollect(obj, parentKey);

  // Now render grouped fields
  const fields: JSX.Element[] = [];
  Object.entries(fieldsByCategory).forEach(([category, categoryFields]) => {
    // Add category header
    fields.push(
      <div key={`category-${category}`} className="font-bold text-foreground mb-1 text-xs">
        {category}
      </div>
    );

    // Add all fields for this category
    categoryFields.forEach((field) => {
      fields.push(
        <div key={field.fullKey} className="flex items-start gap-x-2 ml-6 text-xs mb-1">
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="cursor-pointer font-medium text-muted-foreground hover:underline">
                  {field.fieldName}:
                </span>
              </TooltipTrigger>
              <TooltipContent
                side="top"
                align="start"
                className="w-64 bg-popover p-2 rounded-md shadow-md border"
              >
                <p className="text-sm whitespace-normal mt-1">
                  {(() => {
                    // fullKey includes the section prefix e.g. "mandatoryRequirements.measurementRange"
                    // but descriptions are fetched & stored without that prefix e.g. "measurementRange"
                    // So we strip the first segment (mandatoryRequirements / optionalRequirements / advancedRequirements).
                    const stripped = field.fullKey.replace(/^(mandatoryRequirements|optionalRequirements|advancedRequirements)\./, "");
                    return (
                      field.fieldDescriptions[stripped] ||
                      field.fieldDescriptions[field.fullKey] ||
                      "No description available"
                    );
                  })()}
                </p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>

          <span className="flex items-center gap-1 break-words flex-wrap">
            {field.isFilled ? (
              <>
                {(() => {
                  // Split by semicolon to handle multiple values in one field
                  const parts = field.displayValue.split(';').map(p => p.trim()).filter(p => p);

                  const hasStandardMarker = (s: string) =>
                    s.includes('(STANDARD)') || s.includes('[Standard]') || s.includes('[Standands]');

                  // If ANY part carries the standard marker, the whole field came from
                  // standards — the backend appends (STANDARD) to the full string so
                  // only the last semicolon-part gets it after splitting.
                  const isFieldFromStandards = parts.some(hasStandardMarker);

                  const stripMarkers = (s: string) =>
                    s.replace(/\s*\(STANDARD\)\s*/g, '')
                     .replace(/\s*\[Standard\]\s*/g, '')
                     .replace(/\s*\[Standands\]\s*/g, '')
                     .replace(/\s*\([^)]*\)\s*/g, '')  // remove all parenthetical content
                     .trim();

                  return parts.map((part, idx) => {
                    const isStandard = isFieldFromStandards;
                    const cleanValue = stripMarkers(part);

                    return (
                      <span key={idx} className="inline">
                        {idx > 0 && <span className="text-zinc-500 mr-1">;</span>}
                        <span className={isStandard ? "text-sky-400 font-mono" : "text-emerald-400 font-mono"}>
                          {cleanValue}
                        </span>
                        {isStandard && idx === parts.length - 1 && (
                          <span className="ml-1 text-sky-400 font-mono text-xs font-bold">
                            [Standard]
                          </span>
                        )}
                      </span>
                    );
                  });
                })()}
              </>
            ) : (
              <span className="text-rose-400 font-mono">Not specified</span>
            )}
          </span>
        </div>
      );
    });
  });

  return fields;
}


// Props interface
interface LeftSidebarProps {
  validationResult: ValidationResult | null;
  requirementSchema: RequirementSchema | null;
  currentProductType: string | null;
  collectedData: Record<string, unknown>;
  isDocked: boolean;
  setIsDocked: React.Dispatch<React.SetStateAction<boolean>>;
  fieldDescriptions?: Record<string, string>;
  onFieldDescriptionsChange?: (descriptions: Record<string, string>) => void;
  onScroll?: (scrollTop: number) => void;
  initialScrollTop?: number;
}

// Main rendering function


const LeftSidebar = ({
  requirementSchema,
  currentProductType,
  collectedData = {},
  isDocked,
  setIsDocked,
  fieldDescriptions: savedFieldDescriptions,
  onFieldDescriptionsChange,
  onScroll,
  initialScrollTop = 0,
}: LeftSidebarProps) => {
  const [fieldDescriptions, setFieldDescriptions] = useState<Record<string, string>>(savedFieldDescriptions || {});
  const scrollRef = useRef<HTMLDivElement>(null);

  // Restore scroll position on mount only
  useEffect(() => {
    if (initialScrollTop > 0 && scrollRef.current) {
      // Use requestAnimationFrame to ensure DOM is ready
      requestAnimationFrame(() => {
        if (scrollRef.current) {
          scrollRef.current.scrollTop = initialScrollTop;
        }
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Intentionally run only on mount

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    // Prevent saving "0" scroll position when content is hidden/docked
    if (onScroll && !isDocked) {
      onScroll(e.currentTarget.scrollTop);
    }
  };

  // Note: Auto-undock is now controlled by parent component (index.tsx)
  // This ensures the sidebar undocks at the same time as the API response message appears

  useEffect(() => {
    // Update fieldDescriptions when savedFieldDescriptions prop changes
    if (savedFieldDescriptions && Object.keys(savedFieldDescriptions).length > 0) {
      console.log('Using saved field descriptions:', Object.keys(savedFieldDescriptions).length, 'fields');
      setFieldDescriptions(savedFieldDescriptions);
      return;
    }

    async function fetchAllDescriptions() {
      if (!requirementSchema || !currentProductType) return;
      const allKeys = [
        ...getAllLeafKeys(requirementSchema.mandatoryRequirements || {}),
        ...getAllLeafKeys(requirementSchema.optionalRequirements || {}),
        ...getAllLeafKeys(requirementSchema.advancedRequirements || {}),
      ];
      if (allKeys.length === 0) return;

      console.log('No saved descriptions found, fetching from API for', allKeys.length, 'fields');
      try {
        // Single batched request instead of one POST per field: with 50-100+
        // fields per schema, per-field requests queue behind the browser's
        // per-host connection limit even though most are cache hits server-side.
        const newDescriptions = await getFieldDescriptionsBatch(allKeys, currentProductType);
        setFieldDescriptions(newDescriptions);
        console.log('Field descriptions fetched from API:', Object.keys(newDescriptions).length, 'fields');

        // Notify parent component about the new field descriptions
        if (onFieldDescriptionsChange) {
          onFieldDescriptionsChange(newDescriptions);
        }
      } catch (err) {
        console.error("Error fetching field descriptions", err);
      }
    }
    fetchAllDescriptions();
  }, [requirementSchema, currentProductType, savedFieldDescriptions, onFieldDescriptionsChange]);

  // Restore scroll again when schema loads (content might have grown)
  useEffect(() => {
    if (initialScrollTop > 0 && scrollRef.current && requirementSchema) {
      requestAnimationFrame(() => {
        if (scrollRef.current && scrollRef.current.scrollTop === 0) {
          scrollRef.current.scrollTop = initialScrollTop;
        }
      });
    }
  }, [requirementSchema, initialScrollTop]);

  // Restore scroll when undocking
  useEffect(() => {
    if (!isDocked && initialScrollTop > 0 && scrollRef.current) {
      requestAnimationFrame(() => {
        if (scrollRef.current) {
          scrollRef.current.scrollTop = initialScrollTop;
        }
      });
    }
  }, [isDocked, initialScrollTop]);


  return (
    <div className="flex flex-col h-full w-full glass-sidebar">
      {/* Main content */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto custom-visible-scrollbar p-4 space-y-4"
      >
        {requirementSchema &&
          (isDocked ? (
            // Docked view
            <div >

            </div>
          ) : (
            // Expanded view
            <div>
              <div className="text-center mb-4">
                {/* <h2 className="text-sm font-semibold text-foreground">
                  looking for
                </h2> */}
                <h2 className="text-xl font-semibold">
                  <span className="text-gradient inline-block">
                    {prettify(currentProductType || "")}
                  </span>
                </h2>
              </div>

              {requirementSchema.mandatoryRequirements && (
                <div className="mb-6">
                  <div className="bg-[#171717]/80 backdrop-blur-sm rounded-xl p-4 shadow-md border border-white/10">
                    <div className="space-y-3">
                      {renderFlatFieldsList(
                        requirementSchema.mandatoryRequirements,
                        collectedData,
                        fieldDescriptions,
                        "mandatoryRequirements"
                      )}
                    </div>
                  </div>
                </div>
              )}
              {requirementSchema.optionalRequirements && (
                <div className="mb-6">
                  <div className="bg-[#171717]/80 backdrop-blur-sm rounded-xl p-4 shadow-md border border-white/10">
                    <div className="space-y-3">
                      {renderFlatFieldsList(
                        requirementSchema.optionalRequirements,
                        collectedData,
                        fieldDescriptions,
                        "optionalRequirements"
                      )}
                    </div>
                  </div>
                </div>
              )}
              {requirementSchema.advancedRequirements && Object.keys(requirementSchema.advancedRequirements).length > 0 && (
                <div>
                  <div className="bg-[#171717]/80 backdrop-blur-sm rounded-xl p-4 shadow-md border border-white/10">
                    <div className="space-y-3">
                      {renderFlatFieldsList(
                        requirementSchema.advancedRequirements,
                        collectedData,
                        fieldDescriptions,
                        "advancedRequirements"
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}
      </div>
    </div>
  );
};

export default LeftSidebar;