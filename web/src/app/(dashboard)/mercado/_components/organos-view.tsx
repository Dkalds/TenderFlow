"use client";

/**
 * Vista compartida por la ruta `/organos` y por `?vista=organos` del espacio
 * Mercado. Ver la nota en `tendencias-view.tsx` sobre por qué el cuerpo no vive
 * en el `page.tsx` de la ruta.
 *
 * Primero el mapa, después el detalle: el mapa de compradores y la
 * concentración arriba, el perfil del órgano abierto en una franja debajo y el
 * ranking mariposa al final. Hasta 2026-10 eran dos gráficos de barras gemelos,
 * un treemap y una tabla que repetían el mismo top-50 cuatro veces, con el
 * perfil en una columna lateral que sólo existía a partir de `xl` y tras un clic.
 *
 * Es la única de las vistas que lee la URL (`useSearchParams`, para sembrar el
 * filtro con `?organo_q=`, dentro de `_hooks/use-organos-view.ts`). No dependía
 * de ser una ruta sino de la query, y la query sobrevive igual por las dos
 * entradas: el redirect 308 arrastra la entrante, y
 * `/mercado?vista=organos&organo_q=…` la lleva escrita.
 */

import { PanelError } from "@/components/console/panel";

import { useOrganosView } from "../_hooks/use-organos-view";
import { OrganoPerfil } from "./organo-perfil";
import { OrganosCabecera } from "./organos-cabecera";
import { OrganosConcentracion } from "./organos-concentracion";
import { OrganosMapa } from "./organos-mapa";
import { OrganosMariposa } from "./organos-mariposa";

export default function OrganosView() {
  const {
    data,
    items,
    filteredItems,
    puntos,
    medianas,
    mariposa,
    concentracion,
    metrica,
    setMetrica,
    concentracionTop10,
    totalLicitaciones,
    importeMedio,
    importeTotal,
    totalOrganos,
    filter,
    setFilter,
    organoAbierto,
    rangoAbierto,
    abrirOrgano,
    cerrarPerfil,
    detailData,
    detailLoading,
    detailError,
    refetchDetail,
    isLoading,
    error,
    refetch,
  } = useOrganosView();

  if (error) {
    return <PanelError title="No se pudieron cargar los órganos" error={error} onRetry={refetch} />;
  }

  const filtrado = Boolean(filter);
  const ordenTxt = metrica === "count" ? "licitaciones" : "importe";
  const sugerencias = [
    ...(data?.organos?.map((i) => i.organo_contratacion) ?? []),
    ...[...new Set(data?.organos?.map((i) => i.ccaa).filter((c): c is string => c != null) ?? [])],
  ];
  const abierto = organoAbierto ? items.find((i) => i.organo_contratacion === organoAbierto) : undefined;

  return (
    <div className="space-y-4">
      <OrganosCabecera
        concentracionTop10={concentracionTop10}
        totalLicitaciones={totalLicitaciones}
        totalOrganos={totalOrganos}
        importeTotal={importeTotal}
        metrica={metrica}
        onMetricaChange={setMetrica}
        filter={filter}
        onFilterChange={setFilter}
        sugerencias={sugerencias}
        isLoading={isLoading}
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <OrganosMapa
          puntos={puntos}
          medianas={medianas}
          filtrado={filtrado}
          isLoading={isLoading}
          onOrganoClick={abrirOrgano}
        />
        <OrganosConcentracion
          concentracion={concentracion}
          metrica={metrica}
          nItems={filteredItems.length}
          totalOrganos={totalOrganos}
          importeTotal={importeTotal}
          importeMedio={importeMedio}
          isLoading={isLoading}
        />
      </div>

      {organoAbierto && (
        <OrganoPerfil
          organo={organoAbierto}
          rango={rangoAbierto}
          ordenTxt={ordenTxt}
          ccaa={abierto?.ccaa}
          detalle={detailData}
          isLoading={detailLoading}
          error={detailError}
          onRetry={refetchDetail}
          onClose={cerrarPerfil}
        />
      )}

      <OrganosMariposa
        filas={mariposa}
        metrica={metrica}
        onMetricaChange={setMetrica}
        totalOrganos={totalOrganos}
        filtrado={filtrado}
        isLoading={isLoading}
        onOrganoClick={abrirOrgano}
      />
    </div>
  );
}
