# VoxAI GMaps Scraper — Railway Dockerfile
# Multi-stage build: installs Playwright Chromium, runs as non-root user on port 8000.

FROM python:3.12-slim AS base

# System dependencies required by Playwright's bundled Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl gnupg ca-certificates \
    libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 \
    libpangocairo-1.0-0 libatk1.0-0 libcups2 libdbus-1-3 libexpat1 \
    libfontconfig1 libgcc-s1 libglib2.0-0 libgtk-3-0 libnspr4 \
    libstdc++6 libx11-6 libx11-xcb1 libxcb1 libxext6 \
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1001 scraper
WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (Chromium only to keep image size down)
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy application source
COPY --chown=scraper:scraper . .

# Switch to non-root
USER scraper

# Expose port
EXPOSE 8000

# Start FastAPI via uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
