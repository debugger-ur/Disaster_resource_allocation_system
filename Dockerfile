# DRRAS — Disaster Resource Allocation System (web UI + request-review API)
# The app is Python standard library + SQLite, so there are no dependencies to install.
FROM python:3.12-slim

# sqlite3 and the app only need the stdlib; skip pip entirely for a smaller, faster build.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DRRAS_DB_PATH=/data/drras.sqlite3 \
    PORT=8000

WORKDIR /app

# Copy only what the server needs at runtime.
COPY backend/ ./backend/
COPY docs/ ./docs/

# SQLite lives on a mounted volume so requests and the admin password survive
# container rebuilds. Without a volume here, every redeploy wipes the database.
RUN mkdir -p /data \
    && useradd --create-home --shell /usr/sbin/nologin drras \
    && chown -R drras:drras /data /app
USER drras
VOLUME ["/data"]

EXPOSE 8000

# Set the admin password once, before/at first start:
#   docker compose run --rm drras python3 backend/admin_server.py --set-password
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python3 -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/api/health',timeout=4)"

CMD ["python3", "backend/admin_server.py"]
