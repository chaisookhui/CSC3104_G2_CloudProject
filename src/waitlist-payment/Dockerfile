# Build from repository root: docker build -f src/waitlist-payment/Dockerfile -t ticketing-payment .
FROM python:3.15-slim
WORKDIR /app
COPY requirements.txt /tmp/payment-requirements.txt
RUN pip install --no-cache-dir -r /tmp/payment-requirements.txt
COPY src/waitlist-payment/service.py src/waitlist-payment/lifecycle.py src/waitlist-payment/payment_db.py src/waitlist-payment/payment_settings.py src/waitlist-payment/schema.sql /app/
COPY src/waitlist-payment/payment_audit.py src/waitlist-payment/payment_retry.py src/waitlist-payment/payment_traffic.py src/waitlist-payment/payment_monitoring.py src/waitlist-payment/payment_security.py /app/
COPY src/waitlist-payment/payment_serialization.py /app/
COPY src/waitlist-payment/migrations /app/migrations
ENV PYTHONUNBUFFERED=1 PAYMENT_HOST=0.0.0.0
RUN useradd --create-home payment
USER payment
EXPOSE 5004
# Prototype API; run worker from the identical image with command: python service.py worker.
CMD ["python", "service.py", "serve"]
