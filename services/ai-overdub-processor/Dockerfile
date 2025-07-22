FROM python:3.11-slim



# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*


WORKDIR /app

COPY requirements.txt .
# Install Python dependencies
RUN pip install -r requirements.txt

# Copy shared modules
#COPY shared/ ./shared/

# Copy service code
COPY . .


# Create storage directory
RUN mkdir -p /app/storage

RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

#WORKDIR /app/services/ai-overdub-processor

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import torch; import whisper; print('AI service healthy')" || exit 1

CMD ["python", "main.py"]