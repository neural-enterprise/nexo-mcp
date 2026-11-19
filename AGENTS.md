# AGENTS.md

Guía para agentes de código (Claude Code, Codex, etc.) y para quien llegue nuevo al repositorio.
Contexto general y arquitectura: [README.md](README.md). Despliegue: [docs/despliegue.md](docs/despliegue.md).

## Qué es

Servidor MCP de solo lectura que expone los marts de NEXO (PostgreSQL) al comité de dirección de Grupo Neural
a través de Claude. Python 3.12, SDK `mcp`, `psycopg`, `pyjwt`, `azure-identity`, `uvicorn`.
Qué datos se exponen se decide en el repositorio `nexo-dbt`, **no aquí**.

## Comandos

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q          # pruebas (sin BD ni Azure: todo en memoria)
.venv\Scripts\python -m ruff check .       # lint (si está instalado; ver pyproject.toml)
.venv\Scripts\python -m nexo_mcp           # arrancar (ver README para variables de entorno)
```

## Estructura

| Ruta | Contenido |
|---|---|
| `nexo_mcp/__main__.py` | Arranque: carga configuración, monta servidor y uvicorn |
| `nexo_mcp/config.py` | Configuración por variables de entorno (`.env.example`) |
| `nexo_mcp/servidor.py` | Herramientas MCP (`listar_vistas`, `describir_vista`, `consultar_vista`) e instrucciones para el modelo |
| `nexo_mcp/catalogo.py` | Catálogo de vistas a partir del `manifest.json` de dbt |
| `nexo_mcp/consulta.py` | Construcción de SQL parametrizado y validado contra el catálogo |
| `nexo_mcp/db.py` | Ejecución en transacción de solo lectura con timeout |
| `nexo_mcp/auth.py` | Verificación de tokens de Entra ID (tenant, audiencia, scope, rol) |
| `tests/` | Pruebas con `pytest`; `manifest_ejemplo.json` es el catálogo de prueba |

## Reglas que no se negocian

- **Sin SQL libre.** Todo identificador sale del catálogo validado; todo valor va como parámetro. No concatenar SQL.
- **Solo lectura.** No añadir herramientas que escriban ni relajar la transacción de solo lectura, el timeout ni el
  límite de filas.
- **Sin datos personales** en resultados, logs, tests ni fixtures. El registro de auditoría guarda usuario,
  herramienta y parámetros, nunca resultados.
- **Sin secretos en el repo.** Configuración solo por entorno; `.env` está ignorado. `NEXO_MCP_AUTH=desactivada`
  es únicamente para local (exige 127.0.0.1); no tocar esa salvaguarda.
- **No ampliar el alcance de datos aquí.** Exponer un mart nuevo = `meta.expuesto_claude: true` en `nexo-dbt`.
- **Dependencias con versión exacta** en `requirements.txt`; actualizar con PR y pruebas.

## Convenciones

- Código, nombres, docstrings y mensajes en **español** (como el resto del repo); términos del SDK en inglés.
- `from __future__ import annotations` en los módulos, salvo `servidor.py` (el SDK evalúa las anotaciones; ver
  comentario en el fichero).
- Líneas hasta 140 caracteres. Tipado en funciones públicas.
- Cada cambio de comportamiento lleva su prueba. Las pruebas no deben requerir red, PostgreSQL ni Azure.
- Commits pequeños con mensaje claro en español; PR contra `main` con CI en verde (pruebas + `docker build`).

## Antes de dar algo por terminado

1. `pytest -q` en verde.
2. Si tocas `Dockerfile` o `requirements.txt`: `docker build -t nexo-mcp:local .`
3. Si cambias variables de entorno: actualizar `.env.example` y README/`docs/despliegue.md`.
4. Si cambias lo que ve Claude (herramientas, instrucciones, avisos): revisarlo con quien sea dueño del dato.
