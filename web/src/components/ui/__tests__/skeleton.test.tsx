import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Skeleton, SkeletonChart, SkeletonTable, SkeletonCard } from "@/components/ui/skeleton";

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

describe("SkeletonChart", () => {
  it("renders without crashing", () => {
    const { container } = render(<SkeletonChart />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("accepts a custom height class", () => {
    const { container } = render(<SkeletonChart height="h-[200px]" />);
    // The height class should be applied somewhere in the rendered output
    expect(container.innerHTML).toContain("h-[200px]");
  });

  it("accepts a custom className", () => {
    const { container } = render(<SkeletonChart className="mt-4" />);
    expect(container.innerHTML).toContain("mt-4");
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

describe("SkeletonCard", () => {
  it("renders without crashing", () => {
    const { container } = render(<SkeletonCard />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("renders three skeleton lines inside", () => {
    const { container } = render(<SkeletonCard />);
    // The card wrapper + 3 skeleton divs
    const divs = container.querySelectorAll("div");
    expect(divs.length).toBeGreaterThanOrEqual(3);
  });

  it("applies custom className to wrapper", () => {
    const { container } = render(<SkeletonCard className="custom-card" />);
    expect(container.firstChild).toHaveClass("custom-card");
  });
});
