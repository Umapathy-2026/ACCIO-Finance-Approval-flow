#!/bin/bash
# Install ODBC Driver 18 if not already present
if ! command -v odbcinst &> /dev/null; then
    curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
    curl https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.list
    apt-get update -qq
    ACCEPT_EULA=Y apt-get install -y -qq msodbcsql18 unixodbc-dev
fi

gunicorn --config gunicorn.conf.py app:app
