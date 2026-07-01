import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { GanttChart } from "@/components/charts/gantt-chart";

const ITEMS = [
  { id: "a", label: "Fase A", start: "2024-01-01", end: "2024-03-01", progress: 40 },
  { id: "b", label: "Fase B", start: "2024-02-15", end: "2024-05-01", color: "#ff0000" },
];

describe("GanttChart", () => {
  it("shows an empty-state message when there are no items", () => {
    render(<GanttChart items={[]} />);
    expect(screen.getByText("Sin tareas disponibles")).toBeInTheDocument();
  });

  it("renders a labeled bar per item", () => {
    render(<GanttChart items={ITEMS} />);
    expect(screen.getByLabelText("Diagrama de Gantt")).toBeInTheDocument();
    // Each item exposes a role=button bar with its label as accessible name.
    expect(screen.getByRole("button", { name: "Fase A" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fase B" })).toBeInTheDocument();
  });

  it("fires onItemClick when a bar is clicked", () => {
    const onItemClick = vi.fn();
    render(<GanttChart items={ITEMS} onItemClick={onItemClick} />);
    fireEvent.click(screen.getByRole("button", { name: "Fase A" }));
    expect(onItemClick).toHaveBeenCalledWith("a");
  });

  it("fires onItemClick on Enter and Space keydown", () => {
    const onItemClick = vi.fn();
    render(<GanttChart items={ITEMS} onItemClick={onItemClick} />);
    const bar = screen.getByRole("button", { name: "Fase B" });
    fireEvent.keyDown(bar, { key: "Enter" });
    fireEvent.keyDown(bar, { key: " " });
    expect(onItemClick).toHaveBeenCalledTimes(2);
    expect(onItemClick).toHaveBeenCalledWith("b");
  });

  it("ignores unrelated keys", () => {
    const onItemClick = vi.fn();
    render(<GanttChart items={ITEMS} onItemClick={onItemClick} />);
    fireEvent.keyDown(screen.getByRole("button", { name: "Fase A" }), { key: "Escape" });
    expect(onItemClick).not.toHaveBeenCalled();
  });

  it("shows a tooltip on hover and hides it on leave", () => {
    render(<GanttChart items={ITEMS} />);
    const bar = screen.getByRole("button", { name: "Fase A" });
    fireEvent.mouseEnter(bar);
    // Tooltip repeats the label (appears in bar title + tooltip) and shows progress.
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    expect(screen.getByText(/Progreso: 40%/)).toBeInTheDocument();
    fireEvent.mouseLeave(bar);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});
