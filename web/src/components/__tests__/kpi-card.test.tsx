import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import type { LucideIcon } from "lucide-react";
import { EMPTY } from "@/lib/utils";
import { KpiCard } from "@/components/charts/kpi-card";
import { TooltipProvider } from "@/components/ui/tooltip";

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
    // Skeleton renders a div with the shimmer treatment
    const skeleton = container.querySelector('[data-slot="skeleton"]') ?? container.querySelector('.tf-shimmer');
    expect(skeleton).not.toBeNull();
  });

  it("shows trend up arrow when trend is positive", () => {
    const { container } = render(<KpiCard title="Total" value="100" trend={5.3} />);
    // Positive trend pill uses the success token color
    const trendSpan = container.querySelector(".text-success");
    expect(trendSpan).not.toBeNull();
    expect(trendSpan?.textContent).toContain("+5.3%");
  });

  it("shows trend down arrow when trend is negative", () => {
    const { container } = render(<KpiCard title="Total" value="100" trend={-3.2} />);
    const trendSpan = container.querySelector(".text-destructive");
    expect(trendSpan).not.toBeNull();
    expect(trendSpan?.textContent).toContain("-3.2%");
  });

  it("shows anomaly indicator when anomaly={true}", () => {
    // The anomaly badge wraps in a Tooltip, which requires a TooltipProvider
    // ancestor (real usage gets one from components/providers.tsx).
    render(
      <TooltipProvider>
        <KpiCard title="Total" value="100" anomaly={true} />
      </TooltipProvider>,
    );
    // The sr-only text inside the badge mentions the anomaly, same content
    // as the Tooltip.
    expect(screen.getByText(/Anomal.a detectada/)).toBeInTheDocument();
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
    expect(container.querySelector(".text-success")).toBeNull();
    expect(container.querySelector(".text-destructive")).toBeNull();
  });

  it("usa la raya de vacío de la casa cuando no hay valor", () => {
    // `lib/utils.ts` declara `EMPTY = "—"` y el resto de la app la usa; el KPI
    // pintaba un guion corto y era el único sitio que no seguía la convención.
    render(<KpiCard title="Total" />);
    expect(screen.getByText(EMPTY)).toBeInTheDocument();
  });

  it("shows trendLabel alongside trend", () => {
    render(<KpiCard title="Total" value="100" trend={2} trendLabel="vs mes anterior" />);
    expect(screen.getByText("vs mes anterior")).toBeInTheDocument();
  });

  it("renders a keyboard-focusable link with aria-label when href is provided", () => {
    render(<KpiCard title="Vencen 48h" value="3" href="/pipeline-alertas" />);
    const link = screen.getByRole("link", { name: "Vencen 48h: ver detalle" });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/pipeline-alertas");
  });

  it("does not render a link when href is absent", () => {
    render(<KpiCard title="Total" value="100" />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
