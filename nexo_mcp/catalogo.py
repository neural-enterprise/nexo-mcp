"""Catálogo de vistas expuestas a Claude, leído del manifest.json de dbt (repositorio nexo-dbt).

La única decisión de exposición vive en nexo-dbt: `meta.expuesto_claude: true` en el .yml del mart
(nexo-dbt/docs/comite-claude.md). Aquí solo se lee. Además se exige que el modelo esté en models/marts/:
aunque alguien marcase un modelo de staging, este servidor no lo enseñaría (y la base tampoco le daría permiso).
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger(__name__)

Papel = Literal["dimension", "metrica", "tecnica", "control", "otra"]

# Las columnas de los marts se describen empezando por su papel (nexo-dbt/docs/comite-claude.md §2)
_PREFIJOS_PAPEL: dict[str, Papel] = {
    "dimensión.": "dimension",
    "dimension.": "dimension",
    "métrica.": "metrica",
    "metrica.": "metrica",
    "técnica.": "tecnica",
    "tecnica.": "tecnica",
    "control.": "control",
}

# Tipos que se pueden usar como cast explícito de un parámetro (vienen del contrato del mart)
TIPOS_PERMITIDOS = {
    "date", "text", "bigint", "integer", "smallint", "numeric", "boolean",
    "timestamptz", "timestamp", "double precision", "real",
}


@dataclass(frozen=True)
class Columna:
    nombre: str
    tipo: str | None
    papel: Papel
    descripcion: str

    @property
    def es_fecha(self) -> bool:
        return (self.tipo or "").lower() in {"date", "timestamp", "timestamptz"}


@dataclass(frozen=True)
class Vista:
    nombre: str
    esquema: str
    relacion: str  # nombre del objeto en la base (alias de dbt)
    descripcion: str
    grano: str | None
    dueno: str | None
    estado: str | None
    aviso: str | None
    columnas: dict[str, Columna] = field(default_factory=dict)

    def de_papel(self, papel: Papel) -> list[Columna]:
        return [c for c in self.columnas.values() if c.papel == papel]

    def resumen(self) -> dict[str, Any]:
        return {
            "vista": self.nombre,
            "descripcion": _primer_parrafo(self.descripcion),
            "grano": self.grano,
            "dueno_del_dato": self.dueno,
            "estado": self.estado,
            "aviso": self.aviso,
            "dimensiones": [c.nombre for c in self.de_papel("dimension")],
            "metricas": [c.nombre for c in self.de_papel("metrica")],
        }

    def detalle(self) -> dict[str, Any]:
        return {
            **self.resumen(),
            "descripcion": self.descripcion,
            "columnas": [
                {"nombre": c.nombre, "tipo": c.tipo, "papel": c.papel, "descripcion": c.descripcion}
                for c in self.columnas.values()
            ],
        }


def papel_de(descripcion: str) -> Papel:
    inicio = descripcion.strip().lower()
    for prefijo, papel in _PREFIJOS_PAPEL.items():
        if inicio.startswith(prefijo):
            return papel
    return "otra"


def _primer_parrafo(texto: str) -> str:
    texto = texto.strip()
    return texto.split("\n\n", 1)[0].strip()


def catalogo_desde_manifest(manifest: dict[str, Any]) -> dict[str, Vista]:
    vistas: dict[str, Vista] = {}
    for nodo in manifest.get("nodes", {}).values():
        if nodo.get("resource_type") != "model":
            continue
        meta = (nodo.get("config") or {}).get("meta") or nodo.get("meta") or {}
        if meta.get("expuesto_claude") is not True:
            continue
        ruta = (nodo.get("path") or "").replace("\\", "/")
        if not ruta.startswith("marts/"):
            log.warning("Modelo %s marcado como expuesto pero fuera de marts/: se ignora", nodo.get("name"))
            continue
        columnas = {}
        for nombre, col in (nodo.get("columns") or {}).items():
            descripcion = (col.get("description") or "").strip()
            tipo = (col.get("data_type") or "").strip().lower() or None
            columnas[nombre] = Columna(nombre=nombre, tipo=tipo, papel=papel_de(descripcion), descripcion=descripcion)
        nombre = nodo["name"]
        vistas[nombre] = Vista(
            nombre=nombre,
            esquema=nodo["schema"],
            relacion=nodo.get("alias") or nombre,
            descripcion=(nodo.get("description") or "").strip(),
            grano=meta.get("grano"),
            dueno=meta.get("dueno"),
            estado=meta.get("estado"),
            aviso=meta.get("aviso"),
            columnas=columnas,
        )
    return vistas


def _leer_url(url: str, token: Callable[[], str] | None) -> bytes:
    cabeceras = {"x-ms-version": "2023-11-03"}
    if token is not None:
        cabeceras["Authorization"] = f"Bearer {token()}"
    peticion = urllib.request.Request(url, headers=cabeceras)
    with urllib.request.urlopen(peticion, timeout=30) as respuesta:  # noqa: S310 (URL de configuración, https)
        return respuesta.read()


class FuenteCatalogo:
    """Lee el manifest (fichero local o blob de Azure) y lo recarga cada `ttl_segundos`.

    Si una recarga falla, se sigue sirviendo el último catálogo bueno (y se registra el error).
    """

    def __init__(
        self,
        *,
        ruta: str | None = None,
        url: str | None = None,
        token_blob: Callable[[], str] | None = None,
        ttl_segundos: int = 3600,
    ) -> None:
        if not ruta and not url:
            raise ValueError("Hace falta NEXO_MCP_MANIFEST (ruta) o NEXO_MCP_MANIFEST_URL (blob)")
        self._ruta = ruta
        self._url = url
        self._token_blob = token_blob
        self._ttl = ttl_segundos
        self._vistas: dict[str, Vista] | None = None
        self._cargado_en = 0.0

    def _leer(self) -> dict[str, Any]:
        if self._ruta:
            return json.loads(Path(self._ruta).read_text(encoding="utf-8"))
        assert self._url
        return json.loads(_leer_url(self._url, self._token_blob))

    def vistas(self) -> dict[str, Vista]:
        caducado = time.monotonic() - self._cargado_en > self._ttl
        if self._vistas is None or caducado:
            try:
                self._vistas = catalogo_desde_manifest(self._leer())
                self._cargado_en = time.monotonic()
                log.info("Catálogo cargado: %s", sorted(self._vistas))
            except Exception:
                if self._vistas is None:
                    raise
                log.exception("No se pudo recargar el manifest; se mantiene el catálogo anterior")
                self._cargado_en = time.monotonic()
        return self._vistas
