# Cobertura de adjudicaciones por empresa vigilada

`scraper.connectors.watched_company_awards` es una ingesta complementaria al
radar tecnológico. Lee los NIF canónicos de las empresas que algún usuario
tiene en `watchlist_empresas` y recorre el ATOM oficial de PLACSP. Persiste un
expediente solo cuando alguna adjudicación contiene un NIF vigilado, sin exigir
palabras clave ni CPV tecnológico.

La cobertura es prospectiva y observada: no existe una API oficial de búsqueda
por NIF que el conector pueda usar, ni se declara histórico completo. El cursor
propio empieza a contar desde su primera ejecución y solo alcanza entradas aún
disponibles en el feed. Los resultados usan:

- `analysis_universe=watched_company_awards_observed`
- `inclusion_reason=watched_company_award_nif_match`
- un `id_externo` namespaceado para no sobrescribir el expediente del radar TI.

Cuando haga falta recuperar un mes concreto puede ejecutarse manualmente
`python -m scraper.connectors.watched_company_awards --bulk YEAR MONTH`. Es un
backfill idempotente de ese mes y de los NIF vigilados actuales; no convierte la
fuente en un censo histórico.

## Solape con el radar

Un mismo expediente puede estar tanto en el radar tecnológico como en este
universo NIF. Se conserva por separado para no perder los dos criterios de
observación, pero los agregados existentes del radar (`technology_observed` y
las filas históricas previas al linaje) excluyen explícitamente
`watched_company_awards_observed`. Cualquier métrica futura centrada en las
empresas vigiladas debe filtrar exclusivamente ese universo; no debe sumar
ambos para representar una cuota o tamaño de mercado.

Los servicios de dossier/listado de adjudicaciones de una empresa aceptan el
universo explícito `watched_company_awards_observed` para estas métricas NIF.
Su valor por defecto sigue siendo `technology_observed`, por compatibilidad
con las vistas del radar.
