FROM python:3.12-slim

ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
COPY requirements-api.txt ./
RUN python -m pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements-api.txt

COPY pyproject.toml README.md ./
COPY src ./src
COPY templates ./templates

RUN useradd --create-home --uid 10001 appuser && mkdir -p /data && chown -R appuser:appuser /app /data
USER appuser

CMD ["uvicorn", "doc_table_engine.api:app", "--host", "0.0.0.0", "--port", "8000"]
