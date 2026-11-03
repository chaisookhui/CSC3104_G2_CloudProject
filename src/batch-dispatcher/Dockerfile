# Build from the repository root:
# docker build -f src/batch-dispatcher/Dockerfile -t ticketing-batch-dispatcher:local .
FROM python:3.15.0-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DISPATCHER_DATABASE_URL=sqlite:////data/dispatcher.sqlite3
WORKDIR /app

COPY requirements.txt requirements-container.txt ./
RUN python -m pip install --no-cache-dir -r requirements-container.txt && python -m pip check

COPY src/batch-dispatcher/app.py src/batch-dispatcher/dispatcher_logic.py src/batch-dispatcher/state_store.py ./

RUN useradd --create-home --uid 10001 appuser && mkdir /data && chown appuser:appuser /data
USER appuser
VOLUME ["/data"]
EXPOSE 5005

# Override with: python app.py worker (required recovery worker).
CMD ["gunicorn", "--bind", "0.0.0.0:5005", "--workers", "2", "--threads", "4", "--access-logfile", "-", "--error-logfile", "-", "app:create_app()"]
