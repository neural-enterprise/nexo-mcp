"""Ejecución contra NEXO (PostgreSQL de Azure) con el rol de solo lectura del servidor.

Defensa en capas: el rol solo tiene SELECT en los marts expuestos (lo concede dbt), la transacción es de solo
lectura y con tiempo máximo, y la consulta la construye consulta.py (sin SQL libre).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import psycopg
from psycopg import sql


@dataclass
class Resultado:
    filas: list[tuple[Any, ...]]
    frescura: dict[str, Any] | None


class Ejecutor(Protocol):
    async def ejecutar(
        self, consulta: sql.Composed, params: list[Any], frescura: sql.Composed | None
    ) -> Resultado: ...


class EjecutorPostgres:
    def __init__(
        self,
        *,
        host: str,
        dbname: str,
        user: str,
        password: Callable[[], str],
        timeout_ms: int = 15000,
        port: int = 5432,
    ) -> None:
        self._conninfo = {"host": host, "dbname": dbname, "user": user, "port": port, "sslmode": "require"}
        self._password = password  # contraseña fija o token de Entra (caduca: se pide en cada conexión)
        self._timeout_ms = timeout_ms

    async def ejecutar(
        self, consulta: sql.Composed, params: list[Any], frescura: sql.Composed | None
    ) -> Resultado:
        # Una conexión por consulta: tráfico bajo (comité de dirección) y así el token de Entra siempre es nuevo
        async with await psycopg.AsyncConnection.connect(
            **self._conninfo,
            password=self._password(),
            application_name="nexo-mcp",
            connect_timeout=10,
        ) as conn:
            await conn.set_read_only(True)
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        sql.SQL("set local statement_timeout = {}").format(sql.Literal(self._timeout_ms))
                    )
                    await cur.execute(consulta, params)
                    filas = await cur.fetchall()
                    datos_frescura = None
                    if frescura is not None:
                        await cur.execute(frescura)
                        fila = await cur.fetchone()
                        if fila is not None and cur.description:
                            datos_frescura = {d.name: v for d, v in zip(cur.description, fila, strict=True)}
        return Resultado(filas=filas, frescura=datos_frescura)
