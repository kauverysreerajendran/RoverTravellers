# Rover Traveller local setup (Windows PowerShell)
python -m venv env
.\env\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "Created .env from .env.example. Edit DB credentials if needed."
}

python manage.py makemigrations
python manage.py migrate
python manage.py collectstatic --noinput

Write-Host "Setup complete. Run: python manage.py runserver"
