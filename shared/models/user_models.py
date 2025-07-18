# shared/models/user_models.py
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

class SubscriptionTier(Enum):
    FREE = "free"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"

@dataclass
class User:
    user_id: str
    username: str
    subscription_tier: SubscriptionTier
    subscription_expires: datetime
    daily_usage: int
    total_summaries: int
    created_at: datetime
    language: str = 'ru'  # Default language
    last_payment: Optional[datetime] = None

class UsageLimits:
    """Usage limits for different subscription tiers"""
    
    LIMITS = {
        SubscriptionTier.FREE: {
            'daily_summaries': 5,
            'max_video_duration': 1800,  # 30 minutes
            'summary_types': ['SHORT'],
            'priority_processing': False
        },
        SubscriptionTier.PREMIUM: {
            'daily_summaries': 50,
            'max_video_duration': 7200,  # 2 hours
            'summary_types': ['SHORT', 'MEDIUM', 'DETAILED'],
            'priority_processing': True
        },
        SubscriptionTier.ENTERPRISE: {
            'daily_summaries': -1,  # Unlimited
            'max_video_duration': -1,  # Unlimited
            'summary_types': ['SHORT', 'MEDIUM', 'DETAILED'],
            'priority_processing': True
        }
    }