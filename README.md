# nexo-mcp

Servidor **MCP** (Model Context Protocol) para que el **comité de dirección de Grupo Neural** consulte los datos de
**NEXO** desde Claude (claude.ai), como un conector personalizado de la organización.

**Qué** datos se ven se decide en el repositorio **`nexo-dbt`** (`docs/comite-claude.md`). Este repositorio solo
contiene el servidor: herramientas, acceso con Entra ID y despliegue.

## Cómo funciona

```
claude.ai ──OAuth (Entra ID)──▶ nexo-mcp (Azure Container Apps) ──solo lectura──▶ PostgreSQL NEXO · esquema marts
                                    ▲
                                    └── manifest.json de dbt (Blob Storage, lo publica dbt-nightly cada noche)
```

| Capa | Qué protege |
|---|---|
| `meta.expuesto_claude: true` en `nexo-dbt` | Solo esos marts aparecen en el catálogo y solo esos reciben `GRANT SELECT` |
| Rol `nexo_claude` en PostgreSQL | Lectura de los marts marcados; nada más (migración `20261119_26` de `nexo-dbt`) |
| Herramientas sin SQL libre | Claude elige vista, dimensiones, métricas y filtros; todo se valida contra el manifest y los valores van como parámetros |
| Transacción de solo lectura con tiempo máximo | 15 s por defecto, máximo 1000 filas |
| Entra ID | Token válido del tenant, emitido para esta app, con el permiso `Nexo.Leer` y el rol `Nexo.Comite` |
| Registro | Quién llamó a qué herramienta y con qué parámetros (sin resultados) en los logs del Container App |

## Herramientas

| Herramienta | Para qué |
|---|---|
| `listar_vistas` | Vistas disponibles: descripción, grano, dueño, estado, aviso, dimensiones y métricas |
| `describir_vista` | Columnas con tipo, papel (dimensión, métrica, técnica, control) y significado; proceso y reglas |
| `consultar_vista` | Agrupa por dimensiones (con fecha por día, semana, mes, trimestre o año) y **suma** métricas, con filtros. Devuelve filas, frescura (`fecha_corte`…) y aviso |

El papel de cada columna sale de su descripción en el `.yml` de dbt (`Dimensión.`, `Métrica.`, `Técnica.`,
`Control.`). Los porcentajes no se guardan: Claude los calcula a partir de las sumas, igual que Pulso.

## Desarrollo en local

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
```

Para arrancarlo contra tu esquema de desarrollo, sin Entra ID (solo escucha en 127.0.0.1):

```powershell
$env:NEXO_MCP_AUTH = "desactivada"
$env:NEXO_MCP_MANIFEST = "..\nexo-dbt\target\manifest.json"   # tras «dbt parse» en nexo-dbt
$env:NEXO_PG_HOST = "psql-neural-nexo-spc-prod.postgres.database.azure.com"
$env:NEXO_PG_USER = "<usuario>@neural.es"
$env:NEXO_PG_AUTH = "entra"                                     # usa tu «az login»
.venv\Scripts\python -m nexo_mcp
```

Ojo: con `dbt parse --target dev` el manifest apunta a tu esquema `dev_<usuario>`. Para probarlo con Claude Code:
`claude mcp add --transport http nexo http://127.0.0.1:8000/mcp`.

Lint: `.venv\Scripts\python -m ruff check .` (se ejecuta también en CI).

Configuración completa: [.env.example](.env.example). Despliegue: [docs/despliegue.md](docs/despliegue.md).

## Contribuir

Reglas y convenciones en [AGENTS.md](AGENTS.md); seguridad en [SECURITY.md](SECURITY.md). PR contra `main` con CI en
verde (ruff, pruebas y `docker build`). Uso interno de Grupo Neural: ver [LICENSE](LICENSE).

## Antes de abrirlo al comité

- [ ] Migración `20261119_26_rol_nexo_claude.sql` ejecutada (Armando) y PR de `nexo-dbt` en `main`.
- [ ] Despliegue y conector según [docs/despliegue.md](docs/despliegue.md).
- [ ] Visto bueno de la DPD: Claude recibe resultados agregados (sin datos personales) de NEXO.
- [ ] Dueños del dato de cada vista expuesta conformes, en especial con los avisos de las vistas en estado `demo`.
