# Этот файл создает центральный API Gateway для маршрутизации запросов между микросервисами

# services/api-gateway/main.py
import os
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional
import uuid
from urllib.parse import urlparse, parse_qs

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Import shared components
import sys
sys.path.append('/app')
from shared.database import get_database, get_redis
from shared.models import TaskData, TaskType, TaskStatus, User
from shared.utils import generate_task_id, get_priority_from_subscription

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="YouTube Summarizer API Gateway", version="1.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
db = get_database()
redis = get_redis()

# Queue names for different services
QUEUES = {
    'video_processing': 'video_processing_queue',
    'ai_processing': 'ai_processing_queue',
    'audio_processing': 'audio_processing_queue',
    'file_management': 'file_management_queue',
    'ai_overdub_processing': 'ai_overdub_processing_queue'
}

# Pydantic models for API requests
class VideoProcessingRequest(BaseModel):
    user_id: str
    chat_id: int
    youtube_url: str
    processing_type: str = "text_only"  # text_only, frames_only, full_analysis
    file_format: str = "both"  # pdf, markdown, both
    target_language: Optional[str] = None
    message_id: Optional[int] = None

class AudioProcessingRequest(BaseModel):
    user_id: str
    chat_id: int
    audio_type: str  # voice_message, audio_file, video_lipsync
    file_path: Optional[str] = None
    title: str = "Audio Processing"
    target_language: Optional[str] = None
    message_id: Optional[int] = None

class AIConversationRequest(BaseModel):
    user_id: str
    chat_id: int
    message: str
    context: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[int] = None

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None

@app.on_event("startup")
async def startup_event():
    """Initialize connections on startup"""
    try:
        await redis.connect()
        logger.info("✅ API Gateway started successfully")
    except Exception as e:
        logger.error(f"❌ Failed to start API Gateway: {e}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    await redis.disconnect()
    logger.info("API Gateway shut down")

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "service": "YouTube Summarizer API Gateway",
        "status": "running",
        "timestamp": datetime.now().isoformat()
    }

# Замените функцию health_check в services/api-gateway/main.py на эту версию:

@app.get("/health")
async def health_check():
    """Detailed health check"""
    try:
        # Check Redis connection
        redis_status = await redis.redis.ping()
        
        # Check database connection - используем простой запрос без конкретного пользователя
        try:
            # Попробуем получить количество пользователей
            result = db.supabase.table('users').select('user_id', count='exact').limit(1).execute()
            db_status = "connected"
        except Exception as db_error:
            logger.error(f"Database connection failed: {db_error}")
            db_status = "disconnected"
        
        # Check queue sizes
        queue_sizes = {}
        for queue_name, queue_key in QUEUES.items():
            queue_sizes[queue_name] = await redis.get_queue_size(queue_key)
        
        return {
            "status": "healthy",
            "redis": "connected" if redis_status else "disconnected",
            "database": db_status,
            "queues": queue_sizes,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")

def extract_video_id_from_url(url: str) -> str | None:
    """Надежно извлекает ID видео из разных форматов ссылок YouTube."""
    if not url:
        return None
    try:
        parsed_url = urlparse(url)
        if "youtube.com" in parsed_url.hostname:
            if parsed_url.path == '/watch':
                return parse_qs(parsed_url.query)['v'][0]
            elif parsed_url.path.startswith('/embed/'):
                return parsed_url.path.split('/')[2]
        elif "youtu.be" in parsed_url.hostname:
            return parsed_url.path[1:]
    except Exception:
        return None
    return None

@app.post("/api/v1/video/process")
async def process_video(request: VideoProcessingRequest):
    """Process YouTube video"""
    try:
        # --- НОВОЕ: Извлекаем ID сразу после получения запроса ---
        video_id = extract_video_id_from_url(request.youtube_url)
        
        # --- НОВОЕ: Проверяем, что ID был успешно извлечен ---
        if not video_id:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL or could not extract video ID")

        # Get user info
        user = await db.get_user(request.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        if request.processing_type == 'ai_overdub':
            if not request.target_language:
                raise HTTPException(status_code=400, detail="Target language is required for AI Over Dub")
            if request.target_language not in ['ru', 'en', 'es', 'fr']:
                raise HTTPException(status_code=400, detail="Unsupported target language")
        
        # Generate task ID
        task_id = generate_task_id()
        
        # Create task data
        task_data = TaskData(
            task_id=task_id,
            task_type=TaskType.YOUTUBE_PROCESSING, # Этот тип должен быть в вашей модели
            user_id=request.user_id,
            chat_id=request.chat_id,
            status=TaskStatus.PENDING,
            priority=get_priority_from_subscription(user.subscription_tier.value),
            message_id=request.message_id,
            data={
                # --- ИЗМЕНЕНО: Передаем чистый video_id, а не весь URL ---
                "video_id": video_id, 
                "youtube_url": request.youtube_url, # Сохраняем и URL для истории
                "processing_type": request.processing_type,
                "file_format": request.file_format,
                "target_language": request.target_language, 
                "user_language": user.language,
                "title": f"YouTube Video {video_id}" # Можно передать базовый заголовок
            }
        )
        
        # Add to queue
        success = await redis.enqueue_task('video_processing_queue', task_data)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to enqueue task")
        
        # Set initial status
        await redis.set_task_status(task_id, TaskStatus.PENDING)

        if request.processing_type == 'ai_overdub':
            message = f"AI Over Dub task queued successfully for {request.target_language}"
        else:
            message = "Video processing task queued successfully"
        
        return {
            "task_id": task_id,
            "status": "queued",
            "processing_type": request.processing_type,
            "target_language": request.target_language,
            "message": message
        }
        
    except Exception as e:
        logger.error(f"Error processing video: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/video/ai-overdub")
async def process_ai_overdub(request: VideoProcessingRequest):
    """🔥 НОВОЕ: Process YouTube video with AI Over Dub"""
    try:
        # Валидация для AI Over Dub
        if not request.target_language:
            raise HTTPException(status_code=400, detail="Target language is required for AI Over Dub")
        
        if request.target_language not in ['ru', 'en', 'es', 'fr']:
            raise HTTPException(status_code=400, detail="Unsupported target language for AI Over Dub")

        # Извлекаем ID видео
        video_id = extract_video_id_from_url(request.youtube_url)
        
        if not video_id:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL or could not extract video ID")

        # Get user info
        user = await db.get_user(request.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Generate task ID
        task_id = generate_task_id()
        
        # 🔥 НОВОЕ: Создаем AI Over Dub задачу
        task_data = TaskData(
            task_id=task_id,
            task_type=TaskType.YOUTUBE_PROCESSING,
            user_id=request.user_id,
            chat_id=request.chat_id,
            status=TaskStatus.PENDING,
            priority=get_priority_from_subscription(user.subscription_tier.value) + 1,  # Высокий приоритет
            message_id=request.message_id,
            data={
                "video_id": video_id, 
                "youtube_url": request.youtube_url,
                "processing_type": "ai_overdub",  # 🔥 СПЕЦИАЛЬНЫЙ ТИП
                "target_language": request.target_language,
                "file_format": "video",  # Для AI Over Dub всегда видео
                "user_language": user.language,
                "title": f"AI Over Dub {video_id} → {request.target_language}"
            }
        )
        
        # Add to queue
        success = await redis.enqueue_task('video_processing_queue', task_data)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to enqueue AI Over Dub task")
        
        # Set initial status
        await redis.set_task_status(task_id, TaskStatus.PENDING)
        
        return {
            "task_id": task_id,
            "status": "queued",
            "processing_type": "ai_overdub",
            "target_language": request.target_language,
            "message": f"AI Over Dub task queued successfully for {request.target_language}"
        }
        
    except Exception as e:
        logger.error(f"Error processing AI Over Dub: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/task/{task_id}/ai-overdub-status")
async def get_ai_overdub_status(task_id: str):
    """🔥 НОВОЕ: Get detailed AI Over Dub task status with progress"""
    try:
        status = await redis.get_task_status(task_id)
        
        if not status:
            raise HTTPException(status_code=404, detail="AI Over Dub task not found")
        
        # Базовый ответ
        response = {
            "task_id": task_id,
            "status": status.get('status', 'unknown'),
            "result": status.get('result'),
            "error": status.get('error'),
            "created_at": status.get('created_at', ''),
            "updated_at": status.get('updated_at')
        }
        
        # Дополнительная информация для AI Over Dub
        if status.get('result'):
            result = status['result']
            if isinstance(result, str):
                import json
                result = json.loads(result)
            
            # Прогресс AI Over Dub
            if 'overdub_progress' in result:
                response['overdub_progress'] = result['overdub_progress']
            
            # Информация о стадии
            if 'stage' in result:
                response['current_stage'] = result['stage']
                response['stage_progress'] = result.get('progress', 0)
        
        return response
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error getting AI Over Dub task status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/audio/process")
async def process_audio(request: AudioProcessingRequest):
    """Process audio file or voice message"""
    try:
        # Get user info
        user = await db.get_user(request.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Generate task ID
        task_id = generate_task_id()
        
        # Create task data
        task_data = TaskData(
            task_id=task_id,
            task_type=TaskType.AUDIO_PROCESSING,
            user_id=request.user_id,
            chat_id=request.chat_id,
            status=TaskStatus.PENDING,
            priority=get_priority_from_subscription(user.subscription_tier.value),
            message_id=request.message_id,
            data={
                "audio_type": request.audio_type,
                "file_path": request.file_path,
                "title": request.title,
                "target_language": request.target_language,
                "user_language": user.language
            }
        )
        
        # Add to queue
        success = await redis.enqueue_task(QUEUES['audio_processing'], task_data)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to enqueue task")
        
        # Set initial status
        await redis.set_task_status(task_id, TaskStatus.PENDING)
        
        return {
            "task_id": task_id,
            "status": "queued",
            "message": "Audio processing task queued successfully"
        }
        
    except Exception as e:
        logger.error(f"Error processing audio: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/ai/conversation")
async def ai_conversation(request: AIConversationRequest):
    """Handle AI conversation"""
    try:
        # Get user info
        user = await db.get_user(request.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Generate task ID
        task_id = generate_task_id()
        
        # Create task data
        task_data = TaskData(
            task_id=task_id,
            task_type=TaskType.AI_CONVERSATION,
            user_id=request.user_id,
            chat_id=request.chat_id,
            status=TaskStatus.PENDING,
            priority=get_priority_from_subscription(user.subscription_tier.value),
            message_id=request.message_id,
            data={
                "message": request.message,
                "context": request.context,
                "conversation_id": request.conversation_id,
                "user_language": user.language
            }
        )
        
        # Add to queue
        success = await redis.enqueue_task(QUEUES['ai_processing'], task_data)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to enqueue task")
        
        # Set initial status
        await redis.set_task_status(task_id, TaskStatus.PENDING)
        
        return {
            "task_id": task_id,
            "status": "queued",
            "message": "AI conversation task queued successfully"
        }
        
    except Exception as e:
        logger.error(f"Error handling AI conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/task/{task_id}/status")
async def get_task_status(task_id: str):
    """Get task status"""
    print(f"🔍 DEBUG: Getting status for task {task_id}")
    
    try:
        status = await redis.get_task_status(task_id)
        print(f"🔍 DEBUG: Redis returned: {status}")
        print(f"🔍 DEBUG: Type of status: {type(status)}")
        
        if not status:
            print("🔍 DEBUG: Status is None/empty, raising 404")
            raise HTTPException(status_code=404, detail="Task not found")
        
        print(f"🔍 DEBUG: Creating TaskStatusResponse...")
        response = TaskStatusResponse(
            task_id=task_id,
            status=status.get('status', 'unknown'),
            result=status.get('result'),
            error=status.get('error'),
            created_at=status.get('created_at', ''),
            updated_at=status.get('updated_at')
        )
        print(f"🔍 DEBUG: Response created: {response}")
        
        return response
        
    except HTTPException as e:
        print(f"🔍 DEBUG: HTTPException: {e}")
        raise e
    except Exception as e:
        print(f"🔍 DEBUG: Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        logger.error(f"Error getting task status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/queues/status")
async def get_queues_status():
    """Get all queues status"""
    try:
        queues_info = {}
        for queue_name, queue_key in QUEUES.items():
            size = await redis.get_queue_size(queue_key)
            queues_info[queue_name] = {
                "size": size,
                "queue_key": queue_key
            }
        
        return {
            "queues": queues_info,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting queues status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/user/{user_id}")
async def get_user_info(user_id: str):
    """Get user information"""
    print(f"🔍 DEBUG: Looking for user_id = {user_id}")
    
    try:
        user = await db.get_user(user_id)
        print(f"🔍 DEBUG: db.get_user returned: {user}")
        
        if not user:
            print("🔍 DEBUG: User not found, raising 404")
            raise HTTPException(status_code=404, detail="User not found")
        
        return {
            "user_id": user.user_id,
            "username": user.username,
            "subscription_tier": user.subscription_tier.value,
            "daily_usage": user.daily_usage,
            "total_summaries": user.total_summaries,
            "language": user.language,
            "created_at": user.created_at.isoformat()
        }
        
    except HTTPException as e:
        print(f"🔍 DEBUG: HTTPException: {e}")
        raise e
    except Exception as e:
        print(f"🔍 DEBUG: Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)