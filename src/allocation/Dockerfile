# Build from the repository root:
# docker build -f src/allocation/Dockerfile -t ticketing-allocation:local .
FROM python:3.15.0-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt requirements-container.txt ./
RUN python -m pip install --no-cache-dir -r requirements-container.txt && python -m pip check

COPY src/allocation/app.py src/allocation/algorithm.py src/allocation/job_store.py src/allocation/worker.py src/allocation/seat_client.py src/allocation/dispatcher_client.py ./

RUN useradd --create-home --uid 10001 appuser
USER appuser
EXPOSE 5002

# Override with: python worker.py (worker) or python app.py init-db (initialization).
CMD ["gunicorn", "--bind", "0.0.0.0:5002", "--workers", "2", "--threads", "4", "--access-logfile", "-", "--error-logfile", "-", "app:create_app()"]
