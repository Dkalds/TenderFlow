import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import type { LucideIcon } from "lucide-react";
import { KpiCard } from "@/components/charts/kpi-card";

function TestIcon() {
  return (
    <svg data-testid="test-icon" width="16" height="16">
      <circle cx="8" cy="8" r="8" />
    </svg>
  );
}

describe("KpiCard", () => {
  it("renders title and value text", () => {
    render(<KpiCard title="Total" value="1.234" />);
    expect(screen.getByText("Total")).toBeInTheDocument();
    expect(screen.getByText("1.234")).toBeInTheDocument();
  });

  it("shows loading skeleton when loading={true}", () => {
    const { container } = render(<KpiCard title="Total" loading={true} />);
    // Value text should not be present; Skeleton div should be rendered
    expect(screen.queryByText("1.234")).not.toBeInTheDocument();
    // Skeleton renders a div with animate-pulse class or data-slot="skeleton"
    const skeleton = container.querySelector('[data-slot="skeleton"]') ?? container.querySelector('.animate-pulse');
    expect(skeleton).not.toBeNull();
  });

  it("shows trend up arrow when trend is positive", () => {
    const { container } = render(<KpiCard title="Total" value="100" trend={5.3} />);
    // TrendingUp icon renders as svg — check for the green color class
    const trendSpan = container.querySelector(".text-green-600");
    expect(trendSpan).not.toBeNull();
    expect(trendSpan?.textContent).toContain("+5.3%");
  });

  it("shows trend down arrow when trend is negative", () => {
    const { container } = render(<KpiCard title="Total" value="100" trend={-3.2} />);
    const trendSpan = container.querySelector(".text-red-600");
    expect(trendSpan).not.toBeNull();
    expect(trendSpan?.textContent).toContain("-3.2%");
  });

  it("shows anomaly indicator when anomaly={true}", () => {
    const { container } = render(<KpiCard title="Total" value="100" anomaly={true} />);
    const anomalySpan = container.querySelector('[title]');
    expect(anomalySpan).not.toBeNull();
    // The title mentions anomaly
    expect(anomalySpan?.getAttribute("title")).toContain("noma");
  });

  it("does not show anomaly indicator when anomaly={false} (default)", () => {
    const { container } = render(<KpiCard title="Total" value="100" />);
    // AlertTriangle icon should not be in DOM
    // Check there's no amber-500 background
    const anomalyEl = container.querySelector(".bg-amber-500\\/15");
    expect(anomalyEl).toBeNull();
  });

  it("applies custom className to card element", () => {
    const { container } = render(<KpiCard title="Total" className="my-custom-class" />);
    const card = container.firstChild as HTMLElement;
    expect(card?.className).toContain("my-custom-class");
  });

  it("renders the icon when provided", () => {
    render(<KpiCard title="Total" value="100" icon={TestIcon as unknown as LucideIcon} />);
    expect(screen.getByTestId("test-icon")).toBeInTheDocument();
  });

  it("does not render trend section when trend is undefined", () => {
    const { container } = render(<KpiCard title="Total" value="100" />);
    expect(container.querySelector(".text-green-600")).toBeNull();
    expect(container.querySelector(".text-red-600")).toBeNull();
  });

  it("shows dash when value is not provided", () => {
    render(<KpiCard title="Total" />);
    expect(screen.getByText("-")).toBeInTheDocument();
  });

  it("shows trendLabel alongside trend", () => {
    render(<KpiCard title="Total" value="100" trend={2} trendLabel="vs mes anterior" />);
    expect(screen.getByText("vs mes anterior")).toBeInTheDocument();
  });
});
