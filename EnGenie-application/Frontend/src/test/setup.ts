import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement ResizeObserver, which Radix UI primitives
// (ScrollArea, Tabs) probe for during layout measurement.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// jsdom has no layout engine, so Radix's pointer-based interactions expect
// this to exist even though it's a no-op here.
if (typeof Element.prototype.hasPointerCapture === "undefined") {
  Element.prototype.hasPointerCapture = () => false;
}
if (typeof Element.prototype.scrollIntoView === "undefined") {
  Element.prototype.scrollIntoView = () => {};
}
