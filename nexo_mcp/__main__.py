"""Arranque: python -m nexo_mcp (configuración en variables de entorno, ver .env.example)."""

from __future__ import annotations

import asyncio
import logging
import sys
from urllib.parse import urlparse

import uvicorn
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings

from .auth import VerificadorEntra
from .catalogo import FuenteCatalogo
from .config import Config
from .db import EjecutorPostgres
from .servidor import crear_servidor

ESCOPO_POSTGRES = "https://ossrdbms-aad.database.windows.net/.default"
ESCOPO_STORAGE = "https://storage.azure.com/.default"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = Config.desde_entorno()
    cfg.comprobar()

    credencial = None
    if cfg.pg_auth == "entra" or cfg.manifest_url:
        # Identidad administrada del Container App (o az login en local)
        from azure.identity import DefaultAzureCredential

        credencial = DefaultAzureCredential()

    if cfg.pg_auth == "entra":
        def password() -> str:
            return credencial.get_token(ESCOPO_POSTGRES).token
    else:
        def password() -> str:
            return cfg.pg_password or ""

    catalogo = FuenteCatalogo(
        ruta=cfg.manifest_ruta,
        url=cfg.manifest_url,
        token_blob=(lambda: credencial.get_token(ESCOPO_STORAGE).token) if cfg.manifest_url else None,
        ttl_segundos=cfg.manifest_ttl,
    )
    catalogo.vistas()  # falla al arrancar si no hay manifest legible

    ejecutor = EjecutorPostgres(
        host=cfg.pg_host, dbname=cfg.pg_db, user=cfg.pg_user, password=password, timeout_ms=cfg.timeout_ms
    )

    auth = verificador = None
    seguridad = None
    if not cfg.auth_desactivada:
        verificador = VerificadorEntra(
            tenant_id=cfg.tenant_id, client_id=cfg.client_id, app_id_uri=cfg.app_id_uri,
            scope=cfg.scope, rol_requerido=cfg.rol,
        )
        auth = AuthSettings(
            issuer_url=verificador.emisor,
            resource_server_url=f"{cfg.url_publica.rstrip('/')}/mcp",
            required_scopes=[verificador.scope_completo],
            validate_token_resource=False,  # la audiencia la comprueba VerificadorEntra
        )
        host_publico = urlparse(cfg.url_publica).netloc
        seguridad = TransportSecuritySettings(
            allowed_hosts=[host_publico], allowed_origins=["https://claude.ai", f"https://{host_publico}"]
        )

    servidor = crear_servidor(catalogo, ejecutor, limite_filas=cfg.limite_filas, auth=auth, token_verifier=verificador)
    app = servidor.streamable_http_app(stateless_http=True, transport_security=seguridad, host=cfg.host)
    config = uvicorn.Config(app, host=cfg.host, port=cfg.puerto, proxy_headers=True, forwarded_allow_ips="*")
    # psycopg asíncrono no funciona con el bucle por defecto de Windows (Proactor): en local se usa Selector.
    # En el contenedor (Linux) no cambia nada.
    fabrica = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(uvicorn.Server(config).serve(), loop_factory=fabrica)


if __name__ == "__main__":
    main()
