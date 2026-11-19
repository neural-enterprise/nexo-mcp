# Imagen del servidor MCP de NEXO. Se despliega en Azure Container Apps (docs/despliegue.md).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    NEXO_MCP_HOST=0.0.0.0 NEXO_MCP_PUERTO=8000

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --timeout 60 --retries 10 -r requirements.txt

COPY nexo_mcp/ nexo_mcp/

# Sin privilegios
RUN useradd --create-home --uid 10001 nexo
USER nexo

EXPOSE 8000
CMD ["python", "-m", "nexo_mcp"]
