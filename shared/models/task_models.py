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
    AI_OVERDUB_PROCESSING = "ai_overdub_processing" 



class TaskStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OverDubStage(Enum):
    """Стадии обработки AI Over Dub"""
    TRANSCRIPTION = "transcription"          # 🤖 Рабочий №1: Whisper распознает речь
    TRANSLATION = "translation"              # 🧠 Рабочий №2: Gemini переводит
    TTS_GENERATION = "tts_generation"        # 🗣️ Рабочий №3: Edge TTS озвучивает
    VIDEO_SYNCHRONIZATION = "video_sync"     # 🎬 Рабочий №4: FFmpeg собирает видео
    FINALIZING = "finalizing"                # 📦 Финализация и сохранение

@dataclass
class OverDubProgress:
    """Прогресс выполнения AI Over Dub"""
    current_stage: OverDubStage
    stage_progress: int                      # 0-100% текущей стадии
    total_progress: int                      # 0-100% общего прогресса
    segments_total: int                      # Общее количество сегментов
    segments_processed: int                  # Обработано сегментов
    estimated_time_remaining: Optional[int] = None  # Осталось секунд
    current_action: Optional[str] = None     # Текущее действие
    
    def to_dict(self) -> Dict:
        """Конвертация в словарь для JSON"""
        return {
            'current_stage': self.current_stage.value,
            'stage_progress': self.stage_progress,
            'total_progress': self.total_progress,
            'segments_total': self.segments_total,
            'segments_processed': self.segments_processed,
            'estimated_time_remaining': self.estimated_time_remaining,
            'current_action': self.current_action
        }

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

    overdub_progress: Optional[OverDubProgress] = None

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
        
        # 🔥 НОВОЕ: Сериализация прогресса AI Over Dub
        if self.overdub_progress:
            result['overdub_progress'] = self.overdub_progress.to_dict()

        return result
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TaskData':
        """Create TaskData from dictionary"""
        data['task_type'] = TaskType(data['task_type'])
        data['status'] = TaskStatus(data['status'])
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        
        # 🔥 НОВОЕ: Десериализация прогресса AI Over Dub
        if 'overdub_progress' in data and data['overdub_progress']:
            progress_data = data['overdub_progress']
            data['overdub_progress'] = OverDubProgress(
                current_stage=OverDubStage(progress_data['current_stage']),
                stage_progress=progress_data['stage_progress'],
                total_progress=progress_data['total_progress'],
                segments_total=progress_data['segments_total'],
                segments_processed=progress_data['segments_processed'],
                estimated_time_remaining=progress_data.get('estimated_time_remaining'),
                current_action=progress_data.get('current_action')
            )
        
        return cls(**data)
    
    # 🔥 НОВОЕ: Специальные функции для AI Over Dub
def create_ai_overdub_task(
    task_id: str,
    user_id: str, 
    chat_id: int,
    frames_data: list,
    target_language: str,
    title: str,
    video_path: Optional[str] = None,
    transcript: Optional[str] = None,
    message_id: Optional[int] = None
) -> TaskData:
    """Создает задачу AI Over Dub с правильными параметрами"""
    
    return TaskData(
        task_id=task_id,
        task_type=TaskType.AI_OVERDUB_PROCESSING,
        user_id=user_id,
        chat_id=chat_id,
        status=TaskStatus.PENDING,
        priority=3,  # Высокий приоритет для AI Over Dub
        message_id=message_id,
        data={
            'frames_data': frames_data,
            'target_language': target_language,
            'title': title,
            'video_path': video_path,
            'transcript': transcript,
            'processing_type': 'ai_overdub',
            'created_for': 'ai_overdub_pipeline'
        },
        overdub_progress=OverDubProgress(
            current_stage=OverDubStage.TRANSCRIPTION,
            stage_progress=0,
            total_progress=0,
            segments_total=len(frames_data),
            segments_processed=0,
            current_action="Initializing AI Over Dub pipeline..."
        )
    )

def update_overdub_progress(
    task_data: TaskData,
    stage: OverDubStage,
    stage_progress: int,
    segments_processed: int = None,
    action: str = None
) -> TaskData:
    """Обновляет прогресс AI Over Dub задачи"""
    
    # Маппинг стадий на общий прогресс
    stage_weights = {
        OverDubStage.TRANSCRIPTION: (0, 20),      # 0-20%
        OverDubStage.TRANSLATION: (20, 40),       # 20-40% 
        OverDubStage.TTS_GENERATION: (40, 80),    # 40-80%
        OverDubStage.VIDEO_SYNCHRONIZATION: (80, 95),  # 80-95%
        OverDubStage.FINALIZING: (95, 100)       # 95-100%
    }
    
    start_percent, end_percent = stage_weights[stage]
    stage_range = end_percent - start_percent
    total_progress = start_percent + (stage_progress * stage_range // 100)
    
    if task_data.overdub_progress:
        task_data.overdub_progress.current_stage = stage
        task_data.overdub_progress.stage_progress = stage_progress
        task_data.overdub_progress.total_progress = total_progress
        
        if segments_processed is not None:
            task_data.overdub_progress.segments_processed = segments_processed
        
        if action:
            task_data.overdub_progress.current_action = action
        
        # Примерная оценка времени
        if segments_processed and task_data.overdub_progress.segments_total:
            remaining_segments = task_data.overdub_progress.segments_total - segments_processed
            # Примерно 2-3 секунды на сегмент
            task_data.overdub_progress.estimated_time_remaining = remaining_segments * 2
    
    return task_data