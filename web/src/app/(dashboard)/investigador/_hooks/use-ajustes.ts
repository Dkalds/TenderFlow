"use client";

/**
 * Lo que la consola del Investigador recuerda en este navegador: los ajustes de
 * «Opciones avanzadas» y las consultas recientes.
 *
 * Se lee de `localStorage` **tras el montaje**, nunca durante el render: leerlo
 * antes rompía la hidratación. `lista` dice cuándo ya se leyó, para que quien
 * busca espere a los ajustes guardados en vez de pedir primero con los de por
 * defecto y otra vez con los suyos.
 */

import { useCallback, useEffect, useState } from "react";
import {
  DEFAULT_CONFIG,
  MAX_HISTORY,
  loadConfig,
  loadHistory,
  saveConfig,
  saveHistory,
} from "../_lib/config-storage";
import type { InvestigadorConfig } from "../_lib/types";

export interface AjustesInvestigador {
  config: InvestigadorConfig;
  /** Los ajustes guardados ya se han leído. */
  lista: boolean;
  updateConfig: (patch: Partial<InvestigadorConfig>) => void;
  history: string[];
  addHistory: (consulta: string) => void;
}

export function useAjustes(): AjustesInvestigador {
  const [history, setHistory] = useState<string[]>([]);
  const [config, setConfig] = useState<InvestigadorConfig>(DEFAULT_CONFIG);
  const [lista, setLista] = useState(false);

  useEffect(() => {
    setHistory(loadHistory()); // eslint-disable-line react-hooks/set-state-in-effect
    setConfig(loadConfig());
    setLista(true);
  }, []);

  const updateConfig = useCallback((patch: Partial<InvestigadorConfig>) => {
    setConfig((prev) => {
      const next = { ...prev, ...patch };
      saveConfig(next);
      return next;
    });
  }, []);

  const addHistory = useCallback((consulta: string) => {
    setHistory((prev) => {
      const next = [consulta, ...prev.filter((h) => h !== consulta)].slice(0, MAX_HISTORY);
      saveHistory(next);
      return next;
    });
  }, []);

  return { config, lista, updateConfig, history, addHistory };
}
