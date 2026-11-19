from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from psycopg import sql

from nexo_mcp.catalogo import FuenteCatalogo
from nexo_mcp.db import Resultado

MANIFEST = Path(__file__).parent / "manifest_ejemplo.json"


class EjecutorFalso:
    """Sustituye a PostgreSQL: guarda la consulta y devuelve filas fijas."""

    def __init__(self, filas: list[tuple[Any, ...]] | None = None, error: Exception | None = None) -> None:
        self.filas = filas if filas is not None else [("T1", Decimal(10), Decimal(12), 2)]
        self.error = error
        self.llamadas: list[tuple[str, list[Any]]] = []

    async def ejecutar(self, consulta: sql.Composed, params: list[Any], frescura: sql.Composed | None) -> Resultado:
        if self.error:
            raise self.error
        self.llamadas.append((consulta.as_string(), params))
        return Resultado(filas=self.filas, frescura={"fecha_corte": date(2026, 11, 18), "construido_en": None})


@pytest.fixture
def catalogo() -> FuenteCatalogo:
    return FuenteCatalogo(ruta=str(MANIFEST))


@pytest.fixture
def vista(catalogo: FuenteCatalogo):
    return catalogo.vistas()["operaciones__ocupacion"]
