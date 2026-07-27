# Contribuir al proyecto

Guía para contribuir a TenderFlow.

## Configuración inicial

```bash
make dev   # instala deps de desarrollo + pre-commit hooks
```

## Convención de ramas

```
feature/nombre-descriptivo
fix/descripcion-del-bug
refactor/modulo-afectado
docs/tema
chore/tarea
```

## Conventional Commits

Todos los commits deben seguir [Conventional Commits](https://www.conventionalcommits.org/). Configurado en `.commitlintrc.json`.

### Tipos permitidos

`feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`

### Reglas

- **Subject**: nunca vacío, nunca termina en `.`, nunca en UPPER_CASE ni PascalCase.
- **Header**: máximo 100 caracteres.
- **Scope** (opcional): módulo afectado entre paréntesis.

### Ejemplos

```
feat(scraper): agregar parser para formato CODICE 3.0
fix(db): corregir upsert duplicado en licitaciones
test: agregar property tests para normalización
docs(api): documentar endpoint de webhooks
refactor(services): simplificar capa de dominio
```

El changelog se genera automáticamente con `git-cliff` a partir de estos commits (ver `cliff.toml`).

## Pre-commit hooks

Los hooks se instalan con `make dev`. Se ejecutan automáticamente en cada commit.

### Hooks configurados

| Hook                | Qué hace                                    |
|---------------------|---------------------------------------------|
| trailing-whitespace | Elimina espacios finales                    |
| end-of-file-fixer   | Asegura newline al final                    |
| check-yaml/toml     | Valida sintaxis YAML y TOML                 |
| check-merge-conflict| Detecta marcadores de merge sin resolver    |
| check-added-large-files | Bloquea archivos > 1 MB                |
| detect-private-key  | Bloquea claves privadas                     |
| ruff                | Linting con auto-fix                        |
| ruff-format         | Formateo de código                          |
| mypy                | Type checking (scraper, db, scheduler, config, api, shared) |
| codespell           | Corrector ortográfico                       |
| detect-secrets      | Escaneo de secrets con baseline             |
| gitleaks            | Escaneo de secrets (AWS, GCP, JWTs, etc.)   |
| bandit              | Análisis de seguridad                       |
| pip-audit           | Vulnerabilidades en deps (solo en pre-push) |

### Ejecutar manualmente

```bash
make pre-commit              # todos los hooks sobre todos los archivos
pre-commit run --all-files   # equivalente
pre-commit run ruff --all-files  # solo un hook específico
```

**No uses `--no-verify`** para saltear hooks. Es un invariante del proyecto.

## Suite de verificación completa

Antes de abrir un PR, asegurate de que pase:

```bash
make lint && make typecheck && make test-unit
```

O usá el slash-command `/check` si estás en Claude Code.

Si tu cambio toca `web/`, además:

```bash
make web-lint && make web-typecheck && npm --prefix web run test
```

## Checklist para PRs

- [ ] `make lint` pasa sin errores
- [ ] `make typecheck` pasa sin errores
- [ ] `make test-unit` pasa sin errores
- [ ] Si tocaste `web/`: `make web-lint`, `make web-typecheck` y los tests de Vitest pasan
- [ ] Los commits siguen Conventional Commits
- [ ] Si tocaste módulos strict (`config/*`, `db.database`, `db.users`, `shared/*`), el tipado sigue siendo strict
- [ ] Si agregaste un test, el nombre contiene el token correcto para auto-marking (no marcar a mano)
- [ ] Si tocaste migraciones, es una nueva revisión Alembic (nunca modificar migraciones existentes)
- [ ] Si tocaste analítica o datos en `web/`, no fabricaste agregados en cliente (ver `docs/frontend-data-invariants.md`)
