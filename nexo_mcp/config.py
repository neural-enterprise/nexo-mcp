"""Configuración por variables de entorno (ver .env.example). Ningún secreto en el repositorio."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(nombre: str, defecto: str | None = None) -> str | None:
    valor = os.environ.get(nombre, defecto)
    return valor if valor not in ("", None) else defecto


@dataclass(frozen=True)
class Config:
    # Servidor
    host: str
    puerto: int
    url_publica: str | None  # https://<app>.azurecontainerapps.io (sin /mcp)
    auth_desactivada: bool  # solo para pruebas en local (127.0.0.1)

    # Catálogo (manifest de dbt)
    manifest_ruta: str | None
    manifest_url: str | None
    manifest_ttl: int

    # Base de datos
    pg_host: str | None
    pg_db: str
    pg_user: str | None
    pg_auth: str  # "password" | "entra"
    pg_password: str | None
    timeout_ms: int
    limite_filas: int

    # Entra ID
    tenant_id: str | None
    client_id: str | None
    app_id_uri: str | None
    scope: str
    rol: str

    @classmethod
    def desde_entorno(cls) -> Config:
        return cls(
            host=_env("NEXO_MCP_HOST", "127.0.0.1"),
            puerto=int(_env("NEXO_MCP_PUERTO", "8000")),
            url_publica=_env("NEXO_MCP_URL_PUBLICA"),
            auth_desactivada=_env("NEXO_MCP_AUTH", "entra") == "desactivada",
            manifest_ruta=_env("NEXO_MCP_MANIFEST"),
            manifest_url=_env("NEXO_MCP_MANIFEST_URL"),
            manifest_ttl=int(_env("NEXO_MCP_MANIFEST_TTL", "3600")),
            pg_host=_env("NEXO_PG_HOST"),
            pg_db=_env("NEXO_PG_DB", "nexo"),
            pg_user=_env("NEXO_PG_USER"),
            pg_auth=_env("NEXO_PG_AUTH", "entra"),
            pg_password=_env("NEXO_PG_PASSWORD"),
            timeout_ms=int(_env("NEXO_PG_TIMEOUT_MS", "15000")),
            limite_filas=int(_env("NEXO_MCP_LIMITE_FILAS", "1000")),
            tenant_id=_env("NEXO_ENTRA_TENANT_ID"),
            client_id=_env("NEXO_ENTRA_CLIENT_ID"),
            app_id_uri=_env("NEXO_ENTRA_APP_ID_URI"),
            scope=_env("NEXO_ENTRA_SCOPE", "Nexo.Leer"),
            rol=_env("NEXO_ENTRA_ROL", "Nexo.Comite"),
        )

    def comprobar(self) -> None:
        if self.auth_desactivada and self.host not in ("127.0.0.1", "localhost", "::1"):
            raise SystemExit("NEXO_MCP_AUTH=desactivada solo se permite escuchando en 127.0.0.1")
        if not self.auth_desactivada:
            faltan = [
                n for n, v in {
                    "NEXO_MCP_URL_PUBLICA": self.url_publica,
                    "NEXO_ENTRA_TENANT_ID": self.tenant_id,
                    "NEXO_ENTRA_CLIENT_ID": self.client_id,
                    "NEXO_ENTRA_APP_ID_URI": self.app_id_uri,
                }.items() if not v
            ]
            if faltan:
                raise SystemExit(f"Faltan variables de entorno: {', '.join(faltan)}")
        if not self.pg_host or not self.pg_user:
            raise SystemExit("Faltan NEXO_PG_HOST y NEXO_PG_USER")
        if self.pg_auth == "password" and not self.pg_password:
            raise SystemExit("NEXO_PG_AUTH=password necesita NEXO_PG_PASSWORD")
