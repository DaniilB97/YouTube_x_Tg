# Этот файл объединяет все модели для удобного импорта в сервисах

# shared/models/__init__.py
from .user_models import User, SubscriptionTier, UsageLimits
from .video_models import VideoSummary, SummaryType, ProcessingStatus, PaymentRecord
from .task_models import TaskData, TaskType, TaskStatus

__all__ = [
    # User models
    'User', 
    'SubscriptionTier', 
    'UsageLimits',
    
    # Video models
    'VideoSummary', 
    'SummaryType', 
    'ProcessingStatus', 
    'PaymentRecord',
    
    # Task models
    'TaskData', 
    'TaskType', 
    'TaskStatus'
]