# Один образ для всех сервисов приложения (bot, api, migrate).
# Команда выбирается в docker-compose.yml.

# ---------- сборка админки ----------
FROM node:22-alpine AS admin
WORKDIR /admin
COPY admin/package.json admin/package-lock.json ./
RUN npm ci
COPY admin/ ./
RUN npm run build

# ---------- бэкенд ----------
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY backend/pyproject.toml ./
# Сначала зависимости — слой кэшируется, пока не меняется pyproject
RUN python - <<'EOF'
import tomllib, subprocess, sys
deps = tomllib.load(open("pyproject.toml", "rb"))["project"]["dependencies"]
subprocess.check_call([sys.executable, "-m", "pip", "install", *deps])
EOF

COPY backend/ ./
COPY --from=admin /admin/dist /admin/dist

# Справочник аэропортов скачается при первом запросе в /app/.cache
RUN mkdir -p /app/.cache

CMD ["python", "-m", "api.main"]
