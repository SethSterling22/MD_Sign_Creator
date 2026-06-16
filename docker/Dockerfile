# Use an official, optimized lightweight Python base image
FROM python:3.11-slim

# Set environment variables to optimize Python execution inside the container
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Establish the operational directory inside the container
WORKDIR /app

# Copy only requirements first to maximize Docker build caching efficiency
COPY requirements.txt .

# Install dependencies without saving local caches to minimize image size
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application files
COPY signature_service .

# Inform Docker that the container listens on port 5050 at runtime
EXPOSE 5050

# Run the app with Gunicorn, binding to all interfaces on port 5050
CMD ["gunicorn", "--bind", "0.0.0.0:5050", "app:app"]

# docker build -t flaskapp -f docker/Dockerfile .
# docker run -d -p 5001:5050 --name running-flask-container flaskapp
