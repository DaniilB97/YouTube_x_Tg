#Этот класс будет использоваться для передачи задач между сервисами через Redis.

# shared/models/task_models.py
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
import json

class TaskType(Enum):
    YOUTUBE_PROCESSING = "youtube_processing"
    VOICE_PROCESSING = "voice_processing"
    AUDIO_PROCESSING = "audio_processing"
    VIDEO_LIPSYNC = "video_lipsync"
    AI_CONVERSATION = "ai_conversation"
    FILE_GENERATION = "file_generation"
    SUMMARY_GENERATION = "summary_generation" 
    DUB_PROCESSING = "dub_processing"


class TaskStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class TaskData:
    """Universal task data structure for inter-service communication"""
    task_id: str
    task_type: TaskType
    user_id: str
    chat_id: int
    status: TaskStatus
    priority: int = 1  # 1 = low, 5 = high
    created_at: datetime = None
    
    # Task-specific data
    data: Dict[str, Any] = None
    
    # Results
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    
    # Telegram-specific
    message_id: Optional[int] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.data is None:
            self.data = {}
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        result = asdict(self)
        result['task_type'] = self.task_type.value
        result['status'] = self.status.value
        result['created_at'] = self.created_at.isoformat()
        return result
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TaskData':
        """Create TaskData from dictionary"""
        data['task_type'] = TaskType(data['task_type'])
        data['status'] = TaskStatus(data['status'])
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        return cls(**data)