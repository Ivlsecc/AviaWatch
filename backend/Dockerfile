FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY pyproject.toml ./
COPY common ./common
COPY sources ./sources
COPY search ./search
RUN pip install --no-cache-dir .

COPY . .

# Команда задаётся в docker-compose для каждого сервиса (bot, worker, api, scheduler)
CMD ["alembic", "upgrade", "head"]
