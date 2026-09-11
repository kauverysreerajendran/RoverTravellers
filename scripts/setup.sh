#!/usr/bin/env bash
# Rover Traveller local setup (Linux/macOS)
set -e

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example. Edit DB credentials if needed."
fi

python manage.py migrate
python manage.py seed_demo_data
python manage.py collectstatic --noinput

echo "Setup complete. Run: python manage.py runserver"
