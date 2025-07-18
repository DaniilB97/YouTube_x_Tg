# Этот файл создает центральный API Gateway для маршрутизации запросов между микросервисами

# services/api-gateway/main.py
import os
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional
import uuid

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
    'file_management': 'file_management_queue'
}

# Pydantic models for API requests
class VideoProcessingRequest(BaseModel):
    user_id: str
    chat_id: int
    youtube_url: str
    processing_type: str = "text_only"  # text_only, frames_only, full_analysis
    file_format: str = "both"  # pdf, markdown, both
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

@app.get("/health")
async def health_check():
    """Detailed health check"""
    try:
        # Check Redis connection
        redis_status = await redis.redis.ping()
        
        # Check database connection
        test_user = await db.get_user("00000000-0000-0000-0000-000000000000")  # Non-existent user test
        
        # Check queue sizes
        queue_sizes = {}
        for queue_name, queue_key in QUEUES.items():
            queue_sizes[queue_name] = await redis.get_queue_size(queue_key)
        
        return {
            "status": "healthy",
            "redis": "connected" if redis_status else "disconnected",
            "database": "connected",
            "queues": queue_sizes,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")

@app.post("/api/v1/video/process")
async def process_video(request: VideoProcessingRequest):
    """Process YouTube video"""
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
            task_type=TaskType.YOUTUBE_PROCESSING,
            user_id=request.user_id,
            chat_id=request.chat_id,
            status=TaskStatus.PENDING,
            priority=get_priority_from_subscription(user.subscription_tier.value),
            message_id=request.message_id,
            data={
                "youtube_url": request.youtube_url,
                "processing_type": request.processing_type,
                "file_format": request.file_format,
                "user_language": user.language
            }
        )
        
        # Add to queue
        success = await redis.enqueue_task(QUEUES['video_processing'], task_data)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to enqueue task")
        
        # Set initial status
        await redis.set_task_status(task_id, TaskStatus.PENDING)
        
        return {
            "task_id": task_id,
            "status": "queued",
            "message": "Video processing task queued successfully"
        }
        
    except Exception as e:
        logger.error(f"Error processing video: {e}")
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
    try:
        status = await redis.get_task_status(task_id)
        if not status:
            raise HTTPException(status_code=404, detail="Task not found")
        
        return TaskStatusResponse(
            task_id=task_id,
            status=status.get('status', 'unknown'),
            result=status.get('result'),
            error=status.get('error'),
            created_at=status.get('created_at', ''),
            updated_at=status.get('updated_at')
        )
        
    except Exception as e:
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