@echo off
setlocal

set "PIPENV_VENV_IN_PROJECT=1"

pipenv --venv >nul 2>&1
if errorlevel 1 (
  echo Creating backend Pipenv environment in .venv...
  pipenv install
  if errorlevel 1 (
    echo Failed to initialize backend Pipenv environment.
    exit /b 1
  )
)

pipenv run python manage.py runserver 127.0.0.1:8000 --noreload
