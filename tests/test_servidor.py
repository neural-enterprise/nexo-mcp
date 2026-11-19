"""Servidor completo en memoria (cliente MCP real), con la base sustituida por EjecutorFalso."""

import pytest
from mcp import Client

from nexo_mcp.servidor import crear_servidor

from .conftest import EjecutorFalso

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_herramientas_de_solo_lectura(catalogo):
    async with Client(crear_servidor(catalogo, EjecutorFalso())) as cliente:
        herramientas = (await cliente.list_tools()).tools
    assert {h.name for h in herramientas} == {"listar_vistas", "describir_vista", "consultar_vista"}
    assert all(h.annotations and h.annotations.read_only_hint for h in herramientas)


async def test_listar_y_describir(catalogo):
    async with Client(crear_servidor(catalogo, EjecutorFalso())) as cliente:
        lista = await cliente.call_tool("listar_vistas", {})
        detalle = await cliente.call_tool("describir_vista", {"vista": "operaciones__ocupacion"})
        no_existe = await cliente.call_tool("describir_vista", {"vista": "stg_resiplus__estancias"})
    assert [v["vista"] for v in lista.structured_content["vistas"]] == ["operaciones__ocupacion"]
    assert len(detalle.structured_content["columnas"]) == 8
    assert no_existe.is_error
    assert "operaciones__ocupacion" in no_existe.content[0].text


async def test_consultar(catalogo):
    ejecutor = EjecutorFalso()
    async with Client(crear_servidor(catalogo, ejecutor)) as cliente:
        r = await cliente.call_tool(
            "consultar_vista",
            {
                "vista": "operaciones__ocupacion",
                "dimensiones": ["territorio"],
                "metricas": ["plazas_ocupadas_provisional", "camas_activas"],
                "filtros": [{"columna": "fecha", "operador": ">=", "valor": "2026-11-01"}],
            },
        )
    assert not r.is_error, r.content
    datos = r.structured_content
    assert datos["filas"] == [["T1", 10, 12, 2]]
    assert datos["columnas"] == ["territorio", "plazas_ocupadas_provisional", "camas_activas", "filas"]
    assert datos["frescura"] == {"fecha_corte": "2026-11-18", "construido_en": None}
    assert datos["aviso"] == "Demo. Reglas provisionales."
    assert datos["recortado"] is False
    assert ejecutor.llamadas[0][1] == ["2026-11-01"]


async def test_recorte(catalogo):
    ejecutor = EjecutorFalso(filas=[("T1", 1, 1, 1), ("T2", 1, 1, 1), ("T3", 1, 1, 1)])
    async with Client(crear_servidor(catalogo, ejecutor)) as cliente:
        r = await cliente.call_tool(
            "consultar_vista",
            {"vista": "operaciones__ocupacion", "dimensiones": ["territorio"], "metricas": ["camas_activas"], "limite": 2},
        )
    assert r.structured_content["recortado"] is True
    assert len(r.structured_content["filas"]) == 2


async def test_errores_se_explican_sin_detalles_internos(catalogo):
    async with Client(crear_servidor(catalogo, EjecutorFalso(error=RuntimeError("password=secreto")))) as cliente:
        mal_pedido = await cliente.call_tool(
            "consultar_vista", {"vista": "operaciones__ocupacion", "metricas": ["territorio"]}
        )
        caida = await cliente.call_tool(
            "consultar_vista", {"vista": "operaciones__ocupacion", "metricas": ["camas_activas"]}
        )
    assert mal_pedido.is_error and "para sumar" in mal_pedido.content[0].text
    assert caida.is_error and "secreto" not in caida.content[0].text
