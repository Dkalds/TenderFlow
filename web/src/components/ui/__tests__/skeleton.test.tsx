import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Skeleton, SkeletonTable } from "@/components/ui/skeleton";

describe("Skeleton", () => {
  it("renders without crashing", () => {
    const { container } = render(<Skeleton />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("applies custom className", () => {
    const { container } = render(<Skeleton className="h-4 w-32" />);
    expect(container.firstChild).toHaveClass("h-4");
    expect(container.firstChild).toHaveClass("w-32");
  });

  it("renders as a div", () => {
    const { container } = render(<Skeleton />);
    expect(container.firstChild?.nodeName).toBe("DIV");
  });
});

describe("SkeletonTable", () => {
  it("renders the header row and default 6 data rows", () => {
    const { container } = render(<SkeletonTable />);
    // 1 header + 6 rows = 7 skeleton divs inside the wrapper
    const skeletons = container.querySelectorAll("div > div");
    expect(skeletons.length).toBeGreaterThanOrEqual(7);
  });

  it("renders with custom rows count", () => {
    const { container } = render(<SkeletonTable rows={3} />);
    // 1 header + 3 rows = 4 skeleton divs inside the wrapper
    const skeletons = container.querySelectorAll("div > div");
    expect(skeletons.length).toBeGreaterThanOrEqual(4);
  });

  it("applies custom className to wrapper", () => {
    const { container } = render(<SkeletonTable className="my-4" />);
    expect(container.firstChild).toHaveClass("my-4");
  });
});

describe("Skeleton — manija estable", () => {
  it("lleva data-slot=skeleton además del barrido", () => {
    const { container } = render(<Skeleton />);
    expect(container.firstChild).toHaveAttribute("data-slot", "skeleton");
    expect(container.firstChild).toHaveClass("tf-shimmer");
  });
});
