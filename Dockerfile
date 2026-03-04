FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY coordinator/ coordinator/

RUN pip install --no-cache-dir .

ENV HIVE_DB_URL=postgresql://postgres@host.docker.internal:5432/hive

CMD ["python", "-m", "coordinator.mcp.server"]
