# Despliegue en Azure y conexión con claude.ai

Pasos en orden. Los de Azure, Entra ID y PostgreSQL los hace **Armando** (o quien tenga esos permisos); el conector
de claude.ai, un **propietario de la organización en Claude**. Los puntos marcados con 🔎 hay que comprobarlos en la
documentación vigente al hacerlos.

## 1. Registro de aplicación en Entra ID («nexo-mcp»)

1. **App registrations → New registration**: `nexo-mcp`, solo cuentas de este tenant.
2. **Manifest**: `"accessTokenAcceptedVersion": 2` (el servidor valida tokens v2: emisor `…/{tenant}/v2.0`).
3. **Expose an API**: Application ID URI `api://nexo-mcp`; scope delegado `Nexo.Leer` («Leer los datos de NEXO
   expuestos al comité»), consentimiento de administrador.
4. **App roles**: `Nexo.Comite` (tipo *Users/Groups*).
5. **Enterprise applications → nexo-mcp**: *Assignment required* = Sí; asignar el rol `Nexo.Comite` al grupo del
   comité de dirección. Quien no esté en el grupo no obtiene token (y el servidor lo rechaza igualmente).
6. **Cliente para claude.ai**: en la misma app, plataforma *Web* con la URL de retorno de claude.ai 🔎
   (`https://claude.ai/api/mcp/auth_callback`), un *client secret* (caducidad máx. 12 meses, anotar fecha de
   renovación) y permiso de API `api://nexo-mcp/Nexo.Leer` con consentimiento de administrador.

## 2. Manifest de dbt en Blob Storage

1. Cuenta de almacenamiento (privada) y contenedor `nexo-manifest`.
2. Identidad de GitHub de `nexo-dbt` (la del OIDC de los workflows): *Storage Blob Data Contributor* en el contenedor.
3. En `nexo-dbt`, variables del repositorio `NEXO_MANIFEST_STORAGE` (cuenta) y `NEXO_MANIFEST_CONTAINER`
   (`nexo-manifest`). Desde el siguiente `dbt-nightly`, se publica `manifest.json`.

## 3. Container App

1. Imagen: `docker build -t <acr>.azurecr.io/nexo-mcp:<versión> .` y `docker push` (Azure Container Registry).
2. Container App con **identidad administrada del sistema**, ingress externo HTTPS al puerto 8000, mínimo 1 réplica
   (evita el arranque en frío en la primera pregunta).
3. Acceso de la identidad: *AcrPull* en el registro y *Storage Blob Data Reader* en el contenedor del manifest.
4. **Red hasta PostgreSQL**: el servidor hoy solo admite IP de oficina y reglas temporales. Opciones: entorno de
   Container Apps con VNet e *private endpoint* al servidor (recomendado), o regla de firewall para la IP de salida
   fija del entorno.
5. Variables de entorno según [.env.example](../.env.example) (`NEXO_PG_AUTH=entra`, `NEXO_MCP_MANIFEST_URL`,
   `NEXO_MCP_URL_PUBLICA` = la URL del Container App, y los datos de Entra del paso 1). Sin secretos: la base y el
   blob se leen con la identidad administrada.

## 4. Usuario en PostgreSQL

Como administrador de Entra del servidor, conectado a la base `postgres`:

```sql
SELECT * FROM pgaadauth_create_principal('<nombre de la identidad administrada>', false, false);
```

Después, en la base `nexo`, como migración nueva de `nexo-dbt` (`db/migraciones/`, la ejecuta Armando):

```sql
GRANT nexo_claude TO "<nombre de la identidad administrada>";
ALTER ROLE "<nombre de la identidad administrada>" SET default_transaction_read_only = on;
ALTER ROLE "<nombre de la identidad administrada>" SET statement_timeout = '15s';
```

`NEXO_PG_USER` = ese mismo nombre.

## 5. Conector en claude.ai

1. Propietario de la organización: **Configuración de la organización → Conectores → Añadir conector
   personalizado** 🔎.
2. URL: `https://<app>.<region>.azurecontainerapps.io/mcp`.
3. Opciones avanzadas: *Client ID* y *Client secret* del paso 1.6 🔎 (Entra ID no admite el registro dinámico de
   clientes, así que hay que darlos a mano).
4. Cada persona del comité lo activa en su Claude y se identifica con su cuenta de Neural la primera vez.

## 6. Comprobación

- [ ] `GET https://<app>/.well-known/oauth-protected-resource/mcp` devuelve el tenant como servidor de autorización
      y `api://nexo-mcp/Nexo.Leer` como scope.
- [ ] Una persona del grupo: Claude lista `operaciones__ocupacion` y responde a «ocupación por territorio el mes pasado»
      citando la fecha de corte y el aviso de demo.
- [ ] Una persona fuera del grupo: no puede conectar.
- [ ] En los logs del Container App aparecen las llamadas con el usuario y sin resultados.
- [ ] Como `nexo_claude`: `SELECT` en una vista de `staging` o en un mart no marcado da *permission denied*.
