#!/usr/bin/env bash
# Rover Traveller local setup (Linux/macOS)
set -e

python3 -m venv env
source env/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example. Edit DB credentials if needed."
fi

python manage.py makemigrations
python manage.py migrate
python manage.py collectstatic --noinput

echo "Setup complete. Run: python manage.py runserver"
