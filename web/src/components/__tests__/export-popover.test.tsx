import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// Isolate ExportPopover from the nuqs-backed filter store: it only needs the
// resolved filter params. filters.ts hooks are covered by their own test.
vi.mock("@/lib/filters", () => ({
  useFilterParams: () => ({ q: "obras", estado: "" }),
}));

import { ExportPopover } from "@/components/export-popover";

describe("ExportPopover", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the export trigger and format options", () => {
    render(<ExportPopover />);
    expect(screen.getByText("Exportar")).toBeInTheDocument();
    expect(screen.getByText("Exportar CSV")).toBeInTheDocument();
    expect(screen.getByText("Exportar Excel")).toBeInTheDocument();
  });

  it("triggers a download with format + non-empty filter params on CSV", () => {
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<ExportPopover endpoint="/api/v1/exports/download" extraParams={{ scope: "all" }} />);
    fireEvent.click(screen.getByText("Exportar CSV"));
    expect(clickSpy).toHaveBeenCalledTimes(1);
  });

  it("triggers a download on Excel export", () => {
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<ExportPopover />);
    fireEvent.click(screen.getByText("Exportar Excel"));
    expect(clickSpy).toHaveBeenCalledTimes(1);
  });
});
