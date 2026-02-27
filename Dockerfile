FROM python:3.11-slim

# Install system dependencies required by psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Run as non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 10000

# Render injects $PORT; fall back to 10000 for local docker-run
CMD ["sh", "-c", "alembic upgrade head && gunicorn app:app --bind 0.0.0.0:${PORT:-10000} --workers 2 --timeout 60 --access-logfile -"]
