FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/idx-platform

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

FROM base AS test
COPY tests ./tests
COPY airflow ./airflow
RUN pip install --no-cache-dir ".[dev]"
CMD ["python", "-m", "pytest", "-q"]

FROM base AS runtime
COPY sql ./sql
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
