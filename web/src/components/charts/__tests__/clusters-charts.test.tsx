import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { ClustersBarChart, ClustersBoxChart } from "@/components/charts/clusters-charts";

describe("clusters charts", () => {
  it("renders the cluster bar chart without throwing", () => {
    expect(() =>
      render(
        <ClustersBarChart
          data={[
            { label: "Cluster A", n: 40, cluster_id: 0 },
            { label: "Cluster B", n: 25, cluster_id: 1 },
          ]}
        />,
      ),
    ).not.toThrow();
  });

  it("renders the cluster box chart without throwing", () => {
    expect(() =>
      render(
        <ClustersBoxChart
          data={[
            {
              label: "Cluster A",
              _pad: 10,
              _low: 5,
              _boxLow: 20,
              _boxHigh: 30,
              _high: 5,
              min: 10,
              q1: 20,
              median: 25,
              q3: 40,
              max: 50,
              color: "#4f46e5",
            },
          ]}
        />,
      ),
    ).not.toThrow();
  });
});
