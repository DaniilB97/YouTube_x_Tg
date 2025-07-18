#!/bin/bash

# 1. Очистка конфликтующих Docker сетей
echo "🧹 Cleaning up conflicting Docker networks..."
docker network prune -f

# 2. Остановка всех контейнеров проекта
echo "🛑 Stopping existing containers..."
docker compose down --remove-orphans

# 3. Принудительная очистка (если нужно)
echo "🗑️ Removing conflicting networks (if any)..."
docker network ls | grep youtube-summarizer && docker network rm $(docker network ls -q --filter name=youtube-summarizer) || echo "No conflicting networks found"

# 4. Пересборка образов
echo "🔨 Rebuilding images..."
docker compose build --no-cache ai-processor

# 5. Запуск сервисов по одному для диагностики
echo "🚀 Starting Redis first..."
docker compose up -d redis
sleep 10

echo "🚀 Starting Ollama..."
docker compose up -d ollama
sleep 20

echo "🚀 Starting other services..."
docker compose up -d api-gateway video-processor

echo "🚀 Starting AI processor..."
docker compose up ai-processor

# 6. Проверка статуса сервисов
echo "📊 Checking service status..."
docker compose ps

echo "📋 Checking Ollama models..."
docker exec yt-summarizer-ollama ollama list || echo "Ollama not ready yet"

# 7. Просмотр логов AI processor
echo "📜 AI Processor logs:"
docker compose logs ai-processor

# 8. Тест подключения к Ollama
echo "🔧 Testing Ollama connection..."
docker compose exec ai-processor python test_connection.py