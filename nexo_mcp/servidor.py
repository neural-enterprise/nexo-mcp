"""Servidor MCP de NEXO para el comité de dirección (Grupo Neural).

Tres herramientas, todas de solo lectura:
  - listar_vistas: qué datos hay (solo los marts con meta.expuesto_claude en nexo-dbt).
  - describir_vista: columnas, papel de cada una, dueño del dato y aviso.
  - consultar_vista: agrupar por dimensiones y sumar métricas, con filtros. Sin SQL libre.
"""

# Sin «from __future__ import annotations»: el SDK evalúa las anotaciones de las herramientas y la descripción de
# «limite» depende de una variable local de crear_servidor.
import logging
from typing import Annotated, Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from .catalogo import FuenteCatalogo, Vista
from .consulta import COLUMNA_FILAS, ErrorConsulta, Filtro, Granularidad, Orden, Peticion, a_json, construir, construir_frescura
from .db import Ejecutor

log = logging.getLogger("nexo_mcp.auditoria")

INSTRUCCIONES = f"""\
Datos de NEXO, el almacén de datos de Grupo Neural, para el comité de dirección.

Cómo trabajar:
- Empieza por listar_vistas y describir_vista: solo existen esas vistas y esas columnas. No inventes datos ni columnas.
- consultar_vista agrupa por dimensiones y SUMA métricas. Los porcentajes y medias se calculan después, a partir de
  las sumas (p. ej. ocupación = suma de plazas ocupadas / suma de camas), nunca sumando porcentajes.
- La columna «{COLUMNA_FILAS}» es el nº de filas de la vista en cada grupo (según el grano: p. ej. centro-días).
  Úsala para medias diarias (suma / {COLUMNA_FILAS}) y para detectar huecos.
- En cada respuesta indica de qué fecha son los datos (frescura: fecha_corte) y, si la vista tiene aviso, repítelo
  de forma breve. Si el estado es «demo», dilo claramente.
- Si el resultado viene recortado (recortado = true), dilo y propone filtrar o agrupar más.
- Identifica centros y sociedades por su código además del nombre.
- Son datos agregados, sin datos personales. Si te piden datos de una persona (residente, paciente o empleado),
  explica que este servidor no los tiene.
- Tus respuestas son apoyo a la decisión: ninguna decisión clínica ni de RRHH sin revisión de una persona.
"""

_SOLO_LECTURA = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def _usuario() -> str:
    token = get_access_token()
    if token is None:
        return "local"
    claims = token.claims or {}
    return str(claims.get("preferred_username") or token.subject or "desconocido")


def crear_servidor(
    catalogo: FuenteCatalogo,
    ejecutor: Ejecutor,
    *,
    limite_filas: int = 1000,
    auth: AuthSettings | None = None,
    token_verifier: Any = None,
) -> MCPServer:
    servidor = MCPServer(
        "nexo",
        title="NEXO · Grupo Neural",
        instructions=INSTRUCCIONES,
        version="0.1.0",
        auth=auth,
        token_verifier=token_verifier,
    )

    def _vista(nombre: str) -> Vista:
        vistas = catalogo.vistas()
        if nombre not in vistas:
            raise ToolError(f"No existe la vista «{nombre}». Vistas disponibles: {', '.join(sorted(vistas)) or 'ninguna'}")
        return vistas[nombre]

    @servidor.tool(annotations=_SOLO_LECTURA)
    def listar_vistas() -> dict[str, Any]:
        """Lista las vistas de NEXO que se pueden consultar: descripción, grano, dueño del dato, estado, aviso,
        dimensiones y métricas. Úsala primero."""
        log.info("usuario=%s herramienta=listar_vistas", _usuario())
        return {"vistas": [v.resumen() for v in catalogo.vistas().values()]}

    @servidor.tool(annotations=_SOLO_LECTURA)
    def describir_vista(
        vista: Annotated[str, Field(description="Nombre de la vista, tal como lo da listar_vistas")],
    ) -> dict[str, Any]:
        """Describe una vista: todas sus columnas con tipo, papel (dimensión, métrica, técnica o control) y
        significado, además del proceso, las reglas y el aviso."""
        log.info("usuario=%s herramienta=describir_vista vista=%s", _usuario(), vista)
        return _vista(vista).detalle()

    @servidor.tool(annotations=_SOLO_LECTURA)
    async def consultar_vista(
        vista: Annotated[str, Field(description="Nombre de la vista")],
        metricas: Annotated[list[str], Field(description="Métricas a sumar")] = [],  # noqa: B006
        dimensiones: Annotated[list[str], Field(description="Dimensiones por las que agrupar (vacío = total)")] = [],  # noqa: B006
        filtros: Annotated[list[Filtro], Field(description="Condiciones, todas a la vez (AND)")] = [],  # noqa: B006
        granularidad_fecha: Annotated[
            Granularidad, Field(description="Cómo agrupar las dimensiones de fecha: dia, semana, mes, trimestre o anio")
        ] = "dia",
        orden: Annotated[list[Orden], Field(description="Orden del resultado (por defecto, por las dimensiones)")] = [],  # noqa: B006
        limite: Annotated[int, Field(description=f"Máximo de filas (1–{limite_filas})")] = 200,
    ) -> dict[str, Any]:
        """Consulta una vista agrupando por dimensiones y sumando métricas, con filtros opcionales.
        Devuelve las filas, la frescura del dato (fecha_corte…) y el aviso de la vista."""
        v = _vista(vista)
        peticion = Peticion(
            vista=vista, dimensiones=dimensiones, metricas=metricas, filtros=filtros,
            granularidad_fecha=granularidad_fecha, orden=orden, limite=limite,
        )
        try:
            consulta, params, columnas = construir(peticion, v, limite_max=limite_filas)
        except ErrorConsulta as error:
            raise ToolError(str(error)) from error

        log.info(
            "usuario=%s herramienta=consultar_vista vista=%s dimensiones=%s metricas=%s filtros=%s",
            _usuario(), vista, dimensiones, metricas, [f.model_dump() for f in filtros],
        )
        try:
            resultado = await ejecutor.ejecutar(consulta, params, construir_frescura(v))
        except Exception as error:  # noqa: BLE001 - al modelo no se le dan detalles internos
            log.exception("Error al consultar %s", vista)
            raise ToolError("No se pudo consultar NEXO en este momento. Inténtalo de nuevo más tarde.") from error

        filas = resultado.filas[:limite]
        return {
            "vista": v.nombre,
            "estado": v.estado,
            "aviso": v.aviso,
            "frescura": {k: a_json(x) for k, x in (resultado.frescura or {}).items()},
            "columnas": columnas,
            "filas": [[a_json(x) for x in fila] for fila in filas],
            "recortado": len(resultado.filas) > limite,
        }

    return servidor
