import { redirect } from "next/navigation";

/**
 * Root page — redirects to the default dashboard page (Resumen).
 */
export default function HomePage() {
  redirect("/resumen");
}
