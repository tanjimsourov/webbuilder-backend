# WebBuilder Backend

This repository contains a Django-based backend for a website builder
platform. It is under active restructuring to introduce modular apps,
background processing, payment integrations, and improved security.

## Setup

1. Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

2. Copy `.env.example` to `.env` and fill in required environment variables.

3. Apply migrations and run the development server:

```bash
python manage.py migrate
python manage.py runserver
```

## Deployment

The project uses Docker Compose for local and deployment workflows. For
production, set `DJANGO_DEBUG=0` and configure `DJANGO_SECRET_KEY`,
`DJANGO_ALLOWED_HOSTS`, database credentials, Stripe keys, and Celery/Redis
environment variables.

## Contributing

Install git hooks after cloning:

```bash
pre-commit install
```
