"""Verificación de tokens de Microsoft Entra ID (servidor de recursos OAuth).

claude.ai obtiene el token con el flujo OAuth del conector; este servidor solo lo verifica:
firma (claves públicas del tenant), emisor, audiencia (la app registrada de nexo-mcp), caducidad,
el permiso delegado (scp) y el rol de aplicación que da acceso (asignado al grupo del comité en Entra).
"""

from __future__ import annotations

import logging
from typing import Any

import anyio
import jwt
from mcp.server.auth.provider import AccessToken

log = logging.getLogger(__name__)


class VerificadorEntra:
    def __init__(
        self,
        *,
        tenant_id: str,
        client_id: str,
        app_id_uri: str,
        scope: str,
        rol_requerido: str,
        jwks_client: jwt.PyJWKClient | None = None,
    ) -> None:
        self.emisor = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        self._audiencias = [client_id, app_id_uri]
        self._app_id_uri = app_id_uri.rstrip("/")
        self._scope = scope
        self._rol = rol_requerido
        self._jwks = jwks_client or jwt.PyJWKClient(
            f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys", cache_keys=True, lifespan=3600
        )

    @property
    def scope_completo(self) -> str:
        """Como lo pide el cliente a Entra (api://…/Nexo.Leer); en el token llega solo «Nexo.Leer»."""
        return f"{self._app_id_uri}/{self._scope}"

    def _verificar(self, token: str) -> dict[str, Any]:
        clave = self._jwks.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            clave.key,
            algorithms=["RS256"],
            audience=self._audiencias,
            issuer=self.emisor,
            options={"require": ["exp", "iat", "aud", "iss"]},
            leeway=60,
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = await anyio.to_thread.run_sync(self._verificar, token)
        except jwt.PyJWTError as error:
            log.info("Token rechazado: %s", error)
            return None

        scopes = (claims.get("scp") or "").split()
        if self._scope not in scopes:
            log.info("Token sin el permiso %s (scp=%s)", self._scope, scopes)
            return None
        if self._rol not in (claims.get("roles") or []):
            log.info("Usuario %s sin el rol %s", claims.get("oid"), self._rol)
            return None

        return AccessToken(
            token=token,
            client_id=str(claims.get("azp") or claims.get("appid") or ""),
            scopes=[f"{self._app_id_uri}/{s}" for s in scopes],
            expires_at=int(claims["exp"]),
            subject=claims.get("oid") or claims.get("sub"),
            claims={k: claims.get(k) for k in ("iss", "oid", "preferred_username", "name", "tid")},
        )
