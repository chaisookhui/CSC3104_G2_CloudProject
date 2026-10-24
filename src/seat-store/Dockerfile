# Build from the repository root:
# docker build -f src/seat-store/Dockerfile -t ticketing-seat-store:local .
FROM python:3.15.0-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt requirements-container.txt ./
RUN python -m pip install --no-cache-dir -r requirements-container.txt && python -m pip check

COPY src/seat-store/app.py src/seat-store/db.py src/seat-store/settings.py src/seat-store/store.py src/seat-store/manage.py src/seat-store/workers.py ./
COPY src/seat-store/database/migrations ./database/migrations/

RUN useradd --create-home --uid 10001 appuser
USER appuser
EXPOSE 5003

# Override with: python manage.py worker or python manage.py init-db.
CMD ["gunicorn", "--bind", "0.0.0.0:5003", "--workers", "2", "--threads", "4", "--access-logfile", "-", "--error-logfile", "-", "app:create_app()"]
