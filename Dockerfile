# RTO Risk Scorer - Dockerfile for Render Deployment
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first for better caching
COPY pyproject.toml ./
COPY README.md ./

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Copy application code (frontend included; generated CSVs excluded via .dockerignore)
COPY . .

# Build the full 500-customer dataset into the image so Render
# receives consistent data without a volume
RUN python -m synthetic_data.generator

# Create cache directory and make startup script executable
RUN mkdir -p cache && chmod +x start.sh

# Expose port (Render uses PORT environment variable)
EXPOSE 8000

# Health check via Python standard library (no curl in slim image)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import os,sys,urllib.request; p=os.environ.get('PORT','8000'); sys.exit(0 if urllib.request.urlopen(f'http://localhost:{p}/health').status==200 else 1)"

# Run the application via start.sh (uvicorn on ${PORT:-8000})
CMD ["./start.sh"]
