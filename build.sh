#!/bin/bash
set -o errexit

# Upgrade pip and setuptools
pip install --upgrade pip setuptools wheel

# Install system dependencies for pandas (if needed)
# apt-get update && apt-get install -y libatlas-base-dev gfortran

# Install requirements in two steps
pip install --no-deps Django daphne channels channels-redis redis psycopg2-binary whitenoise gunicorn django-cors-headers asgiref

# Then try to install pandas with specific flags
pip install --no-build-isolation "pandas<2.1"  # Use older, more stable version

# Or skip if it fails and install the rest
if [ $? -ne 0 ]; then
    echo "Pandas installation failed, continuing without it..."
    pip install --no-deps -r requirements.txt --exclude pandas || true
fi

# Django commands
python manage.py collectstatic --noinput
python manage.py migrate