FROM python:3.11-slim

WORKDIR /app

# Install OS deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY platform/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt flask pyjwt

# Copy everything
COPY . .

# Expose port
EXPOSE 8080

# Run startup
CMD ["bash", "startup.sh"]
