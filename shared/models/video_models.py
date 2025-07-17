# shared/models/video_models.py
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict

class SummaryType(Enum):
    SHORT = "short"
    MEDIUM = "medium"
    DETAILED = "detailed"

class ProcessingStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class VideoSummary:
    id: str
    user_id: int
    youtube_url: str
    video_id: str
    title: str
    duration: int
    transcript: str
    summary_short: str
    summary_medium: str
    summary_detailed: str
    language: str
    status: ProcessingStatus
    created_at: datetime
    file_path: Optional[str] = None

@dataclass
class PaymentRecord:
    id: str
    user_id: int
    amount: float
    currency: str
    subscription_tier: str  # Will be SubscriptionTier enum
    stripe_session_id: str
    status: str
    created_at: datetime