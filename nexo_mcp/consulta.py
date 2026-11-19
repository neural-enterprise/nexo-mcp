"""Construcción segura de la consulta de `consultar_vista`.

No hay SQL libre: Claude elige vista, dimensiones, métricas, filtros y orden, y aquí se valida todo contra el
catálogo (manifest de dbt). Los identificadores salen solo del catálogo y van entrecomillados con psycopg.sql;
los valores van siempre como parámetros.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from psycopg import sql
from pydantic import BaseModel, ConfigDict, Field

from .catalogo import TIPOS_PERMITIDOS, Columna, Vista

Valor = str | int | float | bool | None
Granularidad = Literal["dia", "semana", "mes", "trimestre", "anio"]

_TRUNC = {"semana": "week", "mes": "month", "trimestre": "quarter", "anio": "year"}
COLUMNA_FILAS = "filas"


class ErrorConsulta(ValueError):
    """Petición no válida: el mensaje se devuelve tal cual a Claude para que la corrija."""


class Filtro(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columna: Annotated[str, Field(description="Columna de la vista (dimensión, control o técnica)")]
    operador: Annotated[
        Literal["=", "!=", ">", ">=", "<", "<=", "en", "no_en", "entre", "es_nulo", "no_es_nulo"],
        Field(description="«en»/«no_en» llevan lista; «entre» lleva [desde, hasta] inclusive; «es_nulo»/«no_es_nulo» sin valor"),
    ]
    valor: Annotated[
        Valor | list[Valor],
        Field(default=None, description="Fechas en formato AAAA-MM-DD"),
    ] = None


class Orden(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columna: Annotated[str, Field(description=f"Una dimensión pedida, una métrica pedida o «{COLUMNA_FILAS}»")]
    descendente: bool = False


class Peticion(BaseModel):
    vista: str
    dimensiones: list[str] = []
    metricas: list[str] = []
    filtros: list[Filtro] = []
    granularidad_fecha: Granularidad = "dia"
    orden: list[Orden] = []
    limite: int = 200


def _columna(vista: Vista, nombre: str, *, papeles: tuple[str, ...], para: str) -> Columna:
    col = vista.columnas.get(nombre)
    if col is None:
        raise ErrorConsulta(
            f"La columna «{nombre}» no existe en {vista.nombre}. Columnas: {', '.join(vista.columnas)}"
        )
    if col.papel not in papeles:
        validas = [c.nombre for c in vista.columnas.values() if c.papel in papeles]
        raise ErrorConsulta(f"«{nombre}» es {col.papel}; para {para} se puede usar: {', '.join(validas)}")
    return col


def _parametro(col: Columna) -> sql.Composable:
    tipo = (col.tipo or "").lower()
    if tipo in TIPOS_PERMITIDOS:
        return sql.SQL("%s::{}").format(sql.SQL(tipo))
    return sql.SQL("%s")


def _condicion(vista: Vista, filtro: Filtro, params: list[Any]) -> sql.Composable:
    col = _columna(vista, filtro.columna, papeles=("dimension", "control", "tecnica"), para="filtrar")
    ident = sql.Identifier(col.nombre)
    op = filtro.operador
    valor = filtro.valor

    if op in ("es_nulo", "no_es_nulo"):
        return sql.SQL("{} is null" if op == "es_nulo" else "{} is not null").format(ident)

    if op in ("en", "no_en"):
        if not isinstance(valor, list) or not valor:
            raise ErrorConsulta(f"El filtro «{op}» sobre {col.nombre} necesita una lista no vacía")
        if len(valor) > 500:
            raise ErrorConsulta("Como mucho 500 valores en un filtro «en»")
        marcas = sql.SQL(", ").join(_parametro(col) for _ in valor)
        params.extend(valor)
        plantilla = "{} in ({})" if op == "en" else "{} not in ({})"
        return sql.SQL(plantilla).format(ident, marcas)

    if op == "entre":
        if not isinstance(valor, list) or len(valor) != 2:
            raise ErrorConsulta(f"El filtro «entre» sobre {col.nombre} necesita [desde, hasta]")
        params.extend(valor)
        return sql.SQL("{} between {} and {}").format(ident, _parametro(col), _parametro(col))

    if isinstance(valor, list) or valor is None:
        raise ErrorConsulta(f"El filtro «{op}» sobre {col.nombre} necesita un único valor")
    params.append(valor)
    return sql.SQL("{} {} {}").format(ident, sql.SQL(op), _parametro(col))


def construir(peticion: Peticion, vista: Vista, *, limite_max: int) -> tuple[sql.Composed, list[Any], list[str]]:
    """Devuelve (consulta, parámetros, nombres de columnas del resultado)."""
    if not peticion.dimensiones and not peticion.metricas:
        raise ErrorConsulta("Pide al menos una dimensión o una métrica (usa describir_vista para verlas)")
    if not 1 <= peticion.limite <= limite_max:
        raise ErrorConsulta(f"El límite tiene que estar entre 1 y {limite_max}")
    if len(set(peticion.dimensiones)) != len(peticion.dimensiones) or len(set(peticion.metricas)) != len(peticion.metricas):
        raise ErrorConsulta("Hay columnas repetidas en dimensiones o métricas")

    selecciones: list[sql.Composable] = []
    agrupaciones: list[sql.Composable] = []
    salida: list[str] = []

    for nombre in peticion.dimensiones:
        col = _columna(vista, nombre, papeles=("dimension",), para="agrupar")
        ident = sql.Identifier(col.nombre)
        if col.es_fecha and peticion.granularidad_fecha != "dia":
            expr = sql.SQL("date_trunc({}, {})::date").format(sql.Literal(_TRUNC[peticion.granularidad_fecha]), ident)
        else:
            expr = ident
        selecciones.append(sql.SQL("{} as {}").format(expr, ident))
        agrupaciones.append(expr)
        salida.append(col.nombre)

    for nombre in peticion.metricas:
        col = _columna(vista, nombre, papeles=("metrica",), para="sumar")
        ident = sql.Identifier(col.nombre)
        selecciones.append(sql.SQL("sum({}) as {}").format(ident, ident))
        salida.append(col.nombre)

    # Nº de filas de la vista en cada grupo (p. ej. centro-días): sirve para medias y para saber si falta algo
    selecciones.append(sql.SQL("count(*) as {}").format(sql.Identifier(COLUMNA_FILAS)))
    salida.append(COLUMNA_FILAS)

    params: list[Any] = []
    condiciones = [_condicion(vista, f, params) for f in peticion.filtros]

    consulta = sql.SQL("select {} from {}").format(
        sql.SQL(", ").join(selecciones), sql.Identifier(vista.esquema, vista.relacion)
    )
    if condiciones:
        consulta += sql.SQL(" where ") + sql.SQL(" and ").join(condiciones)
    if agrupaciones:
        consulta += sql.SQL(" group by ") + sql.SQL(", ").join(agrupaciones)

    orden = peticion.orden or [Orden(columna=d) for d in peticion.dimensiones]
    if orden:
        claves = []
        for o in orden:
            if o.columna not in salida:
                raise ErrorConsulta(f"Solo se puede ordenar por columnas pedidas: {', '.join(salida)}")
            claves.append(
                sql.SQL("{} {} nulls last").format(sql.Identifier(o.columna), sql.SQL("desc" if o.descendente else "asc"))
            )
        consulta += sql.SQL(" order by ") + sql.SQL(", ").join(claves)

    # Una fila de más para saber si el resultado se ha recortado
    consulta += sql.SQL(" limit {}").format(sql.Literal(peticion.limite + 1))
    return consulta, params, salida


def construir_frescura(vista: Vista) -> sql.Composed | None:
    """max() de cada columna técnica (fecha_corte, fuente_actualizada_en, construido_en...)."""
    tecnicas = vista.de_papel("tecnica")
    if not tecnicas:
        return None
    return sql.SQL("select {} from {}").format(
        sql.SQL(", ").join(
            sql.SQL("max({}) as {}").format(sql.Identifier(c.nombre), sql.Identifier(c.nombre)) for c in tecnicas
        ),
        sql.Identifier(vista.esquema, vista.relacion),
    )


def a_json(valor: Any) -> Any:
    """Tipos de PostgreSQL → JSON (sum() de bigint devuelve Decimal)."""
    from decimal import Decimal

    if isinstance(valor, Decimal):
        return int(valor) if valor == valor.to_integral_value() else float(valor)
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    return valor
