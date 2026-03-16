FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright and dependencies
RUN pip install --no-cache-dir --upgrade pip
COPY app/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
RUN playwright install --with-deps

# Create application directory
WORKDIR /app
COPY app /app/app

# Expose port for FastAPI
EXPOSE 8000

# Command to run the API
CMD ["bash", "-lc", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"]