/**
 * Anomaly detection utilities for time-series data.
 * Detects whether a value deviates significantly from historical data.
 */

/** |current - mean| >= sigma * stddev */
export function isAnomaly(
  current: number,
  history: number[],
  sigma = 2.0,
): boolean {
  if (history.length < 3) return false;
  const mean = history.reduce((a, b) => a + b, 0) / history.length;
  const variance =
    history.reduce((a, b) => a + (b - mean) ** 2, 0) / history.length;
  const std = Math.sqrt(variance);
  const threshold = std > 0 ? sigma * std : mean * 0.1;
  return Math.abs(current - mean) >= threshold;
}
