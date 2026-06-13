# Graphify-first operativo

Esta guia define el uso diario de graphify para navegar arquitectura antes de leer archivos en crudo.

## Comandos practicos

Usa los targets del Makefile:

```bash
make graphify-query Q="donde se calcula la calidad de datos"
make graphify-path A="api.app" B="services.licitaciones"
make graphify-explain TOPIC="scheduler.loop"
make graphify-update
make graphify-update-force
```

Comandos directos equivalentes:

```bash
graphify query "donde se calcula la calidad de datos"
graphify path "api.app" "services.licitaciones"
graphify explain "scheduler.loop"
graphify update .
graphify update . --force
```

## Cuando usar --force

Usa `graphify update . --force` en estos casos:

- Renombraste archivos o modulos.
- Moviste archivos entre paquetes.
- Borraste simbolos/archivos importantes.
- El grafo quedo stale tras refactor estructural.

En cambios pequenos (ediciones internas sin renames/moves), usa `graphify update .` incremental.

## Fallback si graphify no esta instalado

Si el comando `graphify` no existe en tu shell:

1. Documenta en el PR que no se pudo ejecutar graphify en local.
2. Usa navegacion temporal con `rg`/`read_file`.
3. Mantene la regla graphify-first para entornos donde la herramienta este disponible.
