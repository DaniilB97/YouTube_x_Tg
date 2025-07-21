FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY services/ai-overdub-processor/requirements.txt .
RUN pip install -r requirements.txt

# Copy shared modules
#COPY shared/ ./shared/

# Copy service code
COPY . .

# Create storage directory
RUN mkdir -p /app/storage

WORKDIR /app/services/ai-overdub-processor

CMD ["python", "main.py"]