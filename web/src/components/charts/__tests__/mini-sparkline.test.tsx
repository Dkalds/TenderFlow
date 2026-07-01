import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { MiniSparkline } from "@/components/charts/mini-sparkline";

describe("MiniSparkline", () => {
  it("returns null when there are fewer than two points", () => {
    const { container } = render(<MiniSparkline data={[1]} />);
    expect(container.firstChild).toBeNull();
  });

  it("returns null when data is empty", () => {
    const { container } = render(<MiniSparkline data={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders a sized container for a valid series (uptrend)", () => {
    const { container } = render(<MiniSparkline data={[1, 2, 3]} up />);
    const div = container.firstChild as HTMLElement;
    expect(div).not.toBeNull();
    expect(div.style.width).toBe("80px");
    expect(div.style.height).toBe("28px");
  });

  it("renders with the downtrend color and custom size", () => {
    const { container } = render(
      <MiniSparkline data={[3, 2, 1]} up={false} width={120} height={40} className="spark" />,
    );
    const div = container.firstChild as HTMLElement;
    expect(div.className).toContain("spark");
    expect(div.style.width).toBe("120px");
  });
});
