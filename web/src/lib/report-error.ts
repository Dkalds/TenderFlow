/**
 * Centralized error reporting utility.
 * Logs errors to console in development; extend to send to monitoring service.
 */

export function reportError(
  context: string,
  error: unknown,
  extra?: Record<string, unknown>,
): void {
  const message =
    error instanceof Error
      ? error.message
      : typeof error === "string"
        ? error
        : "Unknown error";

  if (process.env.NODE_ENV === "development") {
    console.error(`[${context}]`, message, extra ?? "");
  }

  if (error instanceof Error && error.stack) {
    console.debug(error.stack);
  }
}
