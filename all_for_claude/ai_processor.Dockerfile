# Этот файл создает Docker контейнер для AI Processing Service с PyTorch, Whisper и ffmpeg

# services/ai-processor/Dockerfile
FROM python:3.11-slim

# Установка системных зависимостей для audio/video обработки
RUN apt-get update && apt-get install -y \
    ffmpeg \
    wget \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Создание рабочей директории
WORKDIR /app

# Копирование requirements и установка зависимостей
COPY requirements.txt .

# Установка PyTorch CPU-only для экономии места
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# Установка остальных зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода приложения
COPY . .

# Создание директорий для хранения моделей
RUN mkdir -p /app/models /app/storage

# Создание пользователя для безопасности
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

# Expose порт для health check
EXPOSE 8002

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import torch; import whisper; print('AI service healthy')" || exit 1

# Команда запуска
CMD ["python", "main.py"]