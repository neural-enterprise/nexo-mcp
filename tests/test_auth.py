"""VerificadorEntra con una clave RSA local en lugar de las claves públicas de Entra."""

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from nexo_mcp.auth import VerificadorEntra

pytestmark = pytest.mark.anyio

TENANT = "00000000-0000-0000-0000-000000000001"
CLIENT_ID = "00000000-0000-0000-0000-000000000002"
APP_ID_URI = "api://nexo-mcp"

_clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_otra_clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def anyio_backend():
    return "asyncio"


class JwksFalso:
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=_clave.public_key())


def _verificador():
    return VerificadorEntra(
        tenant_id=TENANT, client_id=CLIENT_ID, app_id_uri=APP_ID_URI,
        scope="Nexo.Leer", rol_requerido="Nexo.Comite", jwks_client=JwksFalso(),
    )


def _token(clave=_clave, **cambios):
    ahora = int(time.time())
    claims = {
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "aud": CLIENT_ID,
        "iat": ahora,
        "exp": ahora + 600,
        "scp": "Nexo.Leer",
        "roles": ["Nexo.Comite"],
        "oid": "usuario-1",
        "preferred_username": "persona@ejemplo.es",
        "azp": "cliente-claude",
    }
    claims.update(cambios)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, clave, algorithm="RS256")


async def test_token_valido():
    acceso = await _verificador().verify_token(_token())
    assert acceso is not None
    assert acceso.scopes == ["api://nexo-mcp/Nexo.Leer"]
    assert acceso.subject == "usuario-1"
    assert acceso.claims["preferred_username"] == "persona@ejemplo.es"


@pytest.mark.parametrize(
    "cambios",
    [
        {"aud": "otra-app"},
        {"iss": "https://login.microsoftonline.com/otro-tenant/v2.0"},
        {"exp": int(time.time()) - 3600},
        {"scp": "User.Read"},
        {"roles": None},
        {"roles": ["Otro.Rol"]},
    ],
)
async def test_tokens_rechazados(cambios):
    assert await _verificador().verify_token(_token(**cambios)) is None


async def test_firma_de_otra_clave():
    assert await _verificador().verify_token(_token(clave=_otra_clave)) is None


async def test_audiencia_app_id_uri():
    assert await _verificador().verify_token(_token(aud=APP_ID_URI)) is not None
