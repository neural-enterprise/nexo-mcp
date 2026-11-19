import pytest

from nexo_mcp.consulta import ErrorConsulta, Filtro, Orden, Peticion, construir, construir_frescura


def _sql(peticion, vista):
    consulta, params, columnas = construir(peticion, vista, limite_max=1000)
    return consulta.as_string(), params, columnas


def test_agrupa_y_suma(vista):
    texto, params, columnas = _sql(
        Peticion(vista=vista.nombre, dimensiones=["territorio"], metricas=["plazas_ocupadas_provisional"]), vista
    )
    assert texto == (
        'select "territorio" as "territorio", sum("plazas_ocupadas_provisional") as "plazas_ocupadas_provisional", '
        'count(*) as "filas" from "marts"."operaciones__ocupacion" group by "territorio" '
        'order by "territorio" asc nulls last limit 201'
    )
    assert params == []
    assert columnas == ["territorio", "plazas_ocupadas_provisional", "filas"]


def test_filtros_parametrizados_con_tipo(vista):
    texto, params, _ = _sql(
        Peticion(
            vista=vista.nombre,
            metricas=["camas_activas"],
            filtros=[
                Filtro(columna="fecha", operador="entre", valor=["2026-10-01", "2026-10-31"]),
                Filtro(columna="codigo_centro", operador="en", valor=["C1", "C2"]),
                Filtro(columna="centro_en_maestro", operador="=", valor=True),
            ],
        ),
        vista,
    )
    assert '"fecha" between %s::date and %s::date' in texto
    assert '"codigo_centro" in (%s::text, %s::text)' in texto
    assert '"centro_en_maestro" = %s::boolean' in texto
    assert params == ["2026-10-01", "2026-10-31", "C1", "C2", True]


def test_granularidad_mes(vista):
    texto, _, _ = _sql(
        Peticion(vista=vista.nombre, dimensiones=["fecha"], metricas=["camas_activas"], granularidad_fecha="mes"), vista
    )
    assert "date_trunc('month', \"fecha\")::date as \"fecha\"" in texto
    assert "group by date_trunc('month', \"fecha\")::date" in texto


def test_orden_por_metrica(vista):
    texto, _, _ = _sql(
        Peticion(
            vista=vista.nombre,
            dimensiones=["codigo_centro"],
            metricas=["camas_activas"],
            orden=[Orden(columna="camas_activas", descendente=True)],
            limite=5,
        ),
        vista,
    )
    assert texto.endswith('order by "camas_activas" desc nulls last limit 6')


@pytest.mark.parametrize(
    "peticion, mensaje",
    [
        (dict(), "al menos una dimensión"),
        (dict(metricas=["no_existe"]), "no existe"),
        (dict(metricas=["territorio"]), "para sumar"),  # una dimensión no se suma
        (dict(dimensiones=["camas_activas"]), "para agrupar"),  # una métrica no agrupa
        (dict(metricas=["camas_activas"], limite=0), "límite"),
        (dict(metricas=["camas_activas"], limite=5000), "límite"),
        (dict(metricas=["camas_activas"], orden=[Orden(columna="territorio")]), "ordenar"),
        (dict(metricas=["camas_activas"], filtros=[Filtro(columna="camas_activas", operador=">", valor=1)]), "filtrar"),
        (dict(metricas=["camas_activas"], filtros=[Filtro(columna="codigo_centro", operador="en", valor="C1")]), "lista"),
        (dict(metricas=["camas_activas"], filtros=[Filtro(columna="fecha", operador="entre", valor=["2026-01-01"])]), "desde, hasta"),
        (dict(metricas=["camas_activas"], filtros=[Filtro(columna="fecha", operador=">=")]), "único valor"),
    ],
)
def test_peticiones_no_validas(vista, peticion, mensaje):
    with pytest.raises(ErrorConsulta, match=mensaje):
        construir(Peticion(vista=vista.nombre, **peticion), vista, limite_max=1000)


def test_identificador_malicioso_no_entra(vista):
    with pytest.raises(ErrorConsulta, match="no existe"):
        construir(Peticion(vista=vista.nombre, metricas=['camas_activas"); drop table x; --']), vista, limite_max=1000)


def test_frescura(vista):
    texto = construir_frescura(vista).as_string()
    assert texto == (
        'select max("fecha_corte") as "fecha_corte", max("construido_en") as "construido_en" '
        'from "marts"."operaciones__ocupacion"'
    )
