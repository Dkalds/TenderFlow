import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PursuitDecisionBadge, PursuitOutcomeBadge, PursuitStatusBadge, daysUntil, formatEur } from "@/components/pursuits/pursuit-presenters";

describe("pursuit presenters", () => {
  it("uses business language rather than internal workflow values", () => {
    render(<><PursuitStatusBadge status="go_no_go" /><PursuitDecisionBadge decision="no_go" /><PursuitOutcomeBadge outcome="won" /></>);
    expect(screen.getByText("Decisión")).toBeInTheDocument();
    expect(screen.getByText("NO-GO")).toBeInTheDocument();
    expect(screen.getByText("Ganada")).toBeInTheDocument();
  });

  it("formats money and deadline urgency for the operating view", () => {
    expect(formatEur(125000)).toMatch(/125[\.\s]000/);
    expect(daysUntil(new Date(Date.now() + 86_400_000).toISOString())).toBe("1 d para cierre");
  });
});
