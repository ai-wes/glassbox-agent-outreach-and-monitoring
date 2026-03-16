FROM python:3.11-slim

# Install system dependencies required for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY api/app/requirements.txt /tmp/requirements.txt
# Upgrade pip and install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/requirements.txt

# Install Playwright browsers
RUN playwright install --with-deps

# Copy application code
WORKDIR /app
COPY api/app /app/app

# Set environment variables for Celery worker
ENV C_FORCE_ROOT=true

# Default command to run the Celery worker
CMD ["bash", "-lc", "celery -A app.celery_app.celery_app worker --loglevel=info --concurrency=1"]