import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import RightPanel from "./RightPanel";
import type { AnalysisResult } from "./types";

// RightPanel fetches live pricing for any ranked product without embedded
// pricing (see the effect around getProductPriceReview) and posts feedback —
// both real network calls in production. Mock the whole api module so
// mounting the component never touches the network.
vi.mock("./api", () => ({
  getProductPriceReview: vi.fn().mockResolvedValue({ results: [] }),
  submitFeedback: vi.fn().mockResolvedValue("thanks"),
  BASE_URL: "http://localhost:8000",
}));

function buildAnalysisResult(overrides: Partial<AnalysisResult> = {}): AnalysisResult {
  return {
    productType: "Pressure Transmitter",
    vendorAnalysis: {
      vendorMatches: [
        {
          productName: "3051CD",
          vendor: "Emerson",
          matchScore: 92,
          requirementsMatch: true,
          reasoning: "Meets all mandatory requirements.",
          limitations: "",
        },
        {
          productName: "266HSH",
          vendor: "ABB",
          matchScore: 85,
          requirementsMatch: true,
          reasoning: "Strong accuracy match.",
          limitations: "IP rating not confirmed.",
        },
      ],
    },
    overallRanking: {
      markdownAnalysis: null,
      rankedProducts: [
        {
          modelFamily: "3051C",
          productType: "Pressure Transmitter",
          rank: 1,
          productName: "3051CD",
          vendor: "Emerson",
          overallScore: 92,
          keyStrengths: "Meets all mandatory requirements.",
          concerns: "",
          requirementsMatch: true,
        },
        {
          modelFamily: "266H",
          productType: "Pressure Transmitter",
          rank: 2,
          productName: "266HSH",
          vendor: "ABB",
          overallScore: 85,
          keyStrengths: "Strong accuracy match.",
          concerns: "IP rating not confirmed.",
          requirementsMatch: true,
        },
      ],
    },
    comparisonTable: {
      specKeys: ["accuracy", "ipRating"],
      rows: [
        {
          vendor: "Emerson",
          productName: "3051CD",
          modelFamily: "3051C",
          values: { accuracy: "±0.065%", ipRating: "IP66" },
        },
        {
          vendor: "ABB",
          productName: "266HSH",
          modelFamily: "266H",
          values: { accuracy: "±0.1%", ipRating: null },
        },
      ],
    },
    ...overrides,
  };
}

function renderRightPanel(analysisResult: AnalysisResult) {
  return render(
    <RightPanel
      analysisResult={analysisResult}
      isDocked={false}
      setIsDocked={() => {}}
    />
  );
}

describe("RightPanel — Compare tab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a Compare tab trigger when a comparison table is present", () => {
    renderRightPanel(buildAnalysisResult());
    expect(screen.getByRole("tab", { name: /compare/i })).toBeInTheDocument();
  });

  it("does not show a Compare tab when comparisonTable is absent", () => {
    renderRightPanel(buildAnalysisResult({ comparisonTable: undefined }));
    expect(screen.queryByRole("tab", { name: /compare/i })).not.toBeInTheDocument();
  });

  it("does not show a Compare tab when comparisonTable has no rows", () => {
    renderRightPanel(
      buildAnalysisResult({ comparisonTable: { specKeys: ["accuracy"], rows: [] } })
    );
    expect(screen.queryByRole("tab", { name: /compare/i })).not.toBeInTheDocument();
  });

  it("does not show a Compare tab when comparisonTable has no spec keys", () => {
    renderRightPanel(
      buildAnalysisResult({
        comparisonTable: {
          specKeys: [],
          rows: [{ vendor: "Emerson", productName: "3051CD", values: {} }],
        },
      })
    );
    expect(screen.queryByRole("tab", { name: /compare/i })).not.toBeInTheDocument();
  });

  it("renders one table column per compared product and one row per spec key", async () => {
    const user = userEvent.setup();
    renderRightPanel(buildAnalysisResult());

    await user.click(screen.getByRole("tab", { name: /compare/i }));

    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row");
    // header row + 2 spec rows (accuracy, ipRating)
    expect(rows).toHaveLength(3);

    // Column headers identify each product/vendor.
    expect(within(table).getByText("3051CD")).toBeInTheDocument();
    expect(within(table).getByText("266HSH")).toBeInTheDocument();
    expect(within(table).getAllByText("Emerson").length).toBeGreaterThan(0);
    expect(within(table).getAllByText("ABB").length).toBeGreaterThan(0);
  });

  it("renders extracted spec values in their correct cells", async () => {
    const user = userEvent.setup();
    renderRightPanel(buildAnalysisResult());

    await user.click(screen.getByRole("tab", { name: /compare/i }));
    const table = await screen.findByRole("table");

    expect(within(table).getByText("±0.065%")).toBeInTheDocument();
    expect(within(table).getByText("IP66")).toBeInTheDocument();
    expect(within(table).getByText("±0.1%")).toBeInTheDocument();
  });

  it("renders a placeholder dash for a spec value the vendor didn't state", async () => {
    const user = userEvent.setup();
    renderRightPanel(buildAnalysisResult());

    await user.click(screen.getByRole("tab", { name: /compare/i }));
    const table = await screen.findByRole("table");

    // ABB's ipRating is null in the fixture -> rendered as an em dash placeholder.
    expect(within(table).getByText("—")).toBeInTheDocument();
  });

  it("humanizes camelCase spec keys into readable row labels", async () => {
    const user = userEvent.setup();
    renderRightPanel(buildAnalysisResult());

    await user.click(screen.getByRole("tab", { name: /compare/i }));
    const table = await screen.findByRole("table");

    expect(within(table).getByText("Ip Rating")).toBeInTheDocument();
  });

  it("still renders the Ranking tab content alongside the Compare tab", () => {
    renderRightPanel(buildAnalysisResult());
    // Ranking tab is the default open tab.
    expect(screen.getByText("3051CD")).toBeInTheDocument();
    expect(screen.getByText("266HSH")).toBeInTheDocument();
  });
});
