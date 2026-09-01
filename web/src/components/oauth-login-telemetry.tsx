"use client";

import * as React from "react";
import { registrarEvento } from "@/lib/analytics";

/** Registra el retorno OAuth una sola vez y elimina su marcador de la URL. */
export function OAuthLoginTelemetry() {
  React.useEffect(() => {
    const oauthLogin = document.cookie
      .split(";")
      .some((entry) => entry.trim() === "oauth_login=1");
    if (!oauthLogin) return;

    registrarEvento("sesion_iniciada", { metodo: "google" });
    document.cookie = "oauth_login=; Max-Age=0; path=/; SameSite=Lax";
  }, []);

  return null;
}
