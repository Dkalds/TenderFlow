import { create } from "zustand";
import { getJSON, setJSON } from "@/lib/storage";

interface DensityState {
  compact: boolean;
  toggleCompact: () => void;
}

export const useDensity = create<DensityState>((set) => ({
  compact: false, // always false on server; synced from localStorage after mount via initDensity()
  toggleCompact: () =>
    set((s) => {
      const next = !s.compact;
      setJSON("density", next ? "compact" : "normal");
      return { compact: next };
    }),
}));

/** Call once in a client useEffect to sync stored preference. */
export function initDensity() {
  if (getJSON<string>("density", "normal") === "compact") {
    useDensity.setState({ compact: true });
  }
}
