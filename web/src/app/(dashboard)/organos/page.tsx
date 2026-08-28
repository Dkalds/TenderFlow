import OrganosView from "../mercado/_components/organos-view";

/**
 * Boundary de ruta. El cuerpo vive en `mercado/_components/organos-view` porque
 * el espacio Mercado monta la misma vista bajo `?vista=organos`.
 *
 * La vista lee `?q=` con `useSearchParams` para sembrar el filtro de órgano: eso
 * no dependía de ser una ruta, sino de la query, y la query sobrevive tanto al
 * redirect 308 (Next arrastra la entrante) como a `/mercado?vista=organos&q=…`.
 */
export default function OrganosPage() {
  return <OrganosView />;
}
