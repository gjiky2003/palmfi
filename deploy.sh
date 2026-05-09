#!/bin/bash
set -e

echo "=== PalmFi AI Lending Company — Deploy ==="

# Check for .env
if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "⚠️  Edit .env with your real secrets before production use!"
fi

# Build and start
echo "Building Docker image..."
docker-compose build

echo "Starting services..."
docker-compose up -d

echo ""
echo "=== Deployed! ==="
echo "  Landing:   http://localhost:8080"
echo "  Admin:     http://localhost:8080/admin/login"
echo "  API:       http://localhost:8080/api/health"
echo ""
echo "  Default admin credentials:"
echo "    Email:    admin@ailending.com"
echo "    Password: admin123"
echo ""
echo "  View logs: docker-compose logs -f"
echo "  Stop:      docker-compose down"
