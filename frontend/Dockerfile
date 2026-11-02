
# Use Python to run our Flask frontend server
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Install Flask and the HTTP server
RUN pip install --no-cache-dir \
    Flask==3.1.3 \
    waitress==3.0.2 \
    requests==2.34.2

# Copy the existing frontend files into the image
COPY frontend/ /app/frontend/

# Document the frontend's internal port
EXPOSE 8080

# Start the frontend server
CMD ["python", "frontend/server.py"]
