#!/bin/bash
# scripts/init-ollama.sh
# Скрипт для инициализации Ollama с автоматической загрузкой модели

set -e

echo "🚀 Starting Ollama initialization..."

# Start Ollama server in background
echo "📡 Starting Ollama server..."
ollama serve &
OLLAMA_PID=$!

# Wait for server to be ready
echo "⏳ Waiting for Ollama server to start..."
max_attempts=30
attempt=0

while [ $attempt -lt $max_attempts ]; do
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "✅ Ollama server is ready!"
        break
    fi
    
    echo "   Attempt $((attempt + 1))/$max_attempts - waiting..."
    sleep 2
    attempt=$((attempt + 1))
done

if [ $attempt -eq $max_attempts ]; then
    echo "❌ Ollama server failed to start within timeout"
    kill $OLLAMA_PID 2>/dev/null || true
    exit 1
fi

# Pull the model if not already present
MODEL_NAME=${OLLAMA_MODEL:-"llama3.1:8b"}
echo "🔍 Checking for model: $MODEL_NAME"

if ollama list | grep -q "$MODEL_NAME"; then
    echo "✅ Model $MODEL_NAME already exists"
else
    echo "📥 Pulling model: $MODEL_NAME"
    if ollama pull "$MODEL_NAME"; then
        echo "✅ Model $MODEL_NAME pulled successfully"
    else
        echo "⚠️ Failed to pull model $MODEL_NAME, but continuing..."
    fi
fi

# Test the model
echo "🧪 Testing model..."
if echo "Hello" | ollama run "$MODEL_NAME" > /dev/null 2>&1; then
    echo "✅ Model test successful"
else
    echo "⚠️ Model test failed, but continuing..."
fi

echo "🎉 Ollama initialization complete!"

# Keep the server running
wait $OLLAMA_PID