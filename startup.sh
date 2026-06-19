#!/bin/bash
# Azure App Service startup script
python -m flask db upgrade 2>/dev/null || true
gunicorn --bind=0.0.0.0:8000 --workers=2 --timeout=120 --access-logfile=- --error-logfile=- app:app