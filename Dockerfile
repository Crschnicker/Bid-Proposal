# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory in the container
WORKDIR /usr/src/app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    build-essential \
    libpq-dev \
    ca-certificates \
    curl \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt ./

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Create necessary directories and set permissions
RUN mkdir -p /usr/src/app/instance && \
    chmod -R 755 /usr/src/app/instance

# Add startup script
COPY startup.sh /usr/src/app/
RUN chmod +x /usr/src/app/startup.sh

# Expose the port the app runs on
EXPOSE 5000

# Use the startup script as the entry point
CMD ["./startup.sh"]