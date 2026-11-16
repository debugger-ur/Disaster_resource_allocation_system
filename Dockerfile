# DRRAS — Python standard library + SQLite. No pip dependencies are required.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DRRAS_DB_PATH=/data/drras.sqlite3 \
    PORT=8000

WORKDIR /app
COPY backend/ ./backend/
COPY docs/ ./docs/
RUN mkdir -p /data

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python3 -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/api/health',timeout=4)"

# Set DRRAS_ADMIN_PASSWORD before the first start, or run once:
#   docker run --rm -it -v drras-data:/data drras python3 backend/app.py --set-password
CMD ["python3", "backend/app.py"]
