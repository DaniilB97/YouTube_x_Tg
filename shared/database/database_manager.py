# Этот файл содержит DatabaseManager для работы с Supabase - точная копия из вашего основного файла

# shared/database/database_manager.py
import os
import logging
from datetime import datetime, timedelta
from typing import Optional, List
from dataclasses import asdict

from supabase import create_client, Client
from shared.models import User, VideoSummary, SubscriptionTier, ProcessingStatus

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Handles all database operations with Supabase"""
    
    def __init__(self):
        self.supabase: Client = create_client(
            os.getenv('SUPABASE_URL'),
            os.getenv('SUPABASE_KEY')
        )
    
    async def get_user(self, user_id: str) -> Optional[User]:
        """Get user from database"""
        try:
            result = self.supabase.table('users').select('*').eq('user_id', user_id).execute()
            
            if result.data:
                row = result.data[0]
                return User(
                    user_id=row['user_id'],
                    username=row['username'],
                    subscription_tier=SubscriptionTier(row['subscription_tier']),
                    subscription_expires=datetime.fromisoformat(row['subscription_expires']),
                    daily_usage=row['daily_usage'],
                    total_summaries=row['total_summaries'],
                    created_at=datetime.fromisoformat(row['created_at']),
                    language=row.get('language', 'ru'),
                    last_payment=datetime.fromisoformat(row['last_payment']) if row['last_payment'] else None
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None
    
    async def create_user(self, user_id: str, username: str, language: str = 'ru') -> User:
        """Create new user"""
        try:
            user = User(
                user_id=user_id,
                username=username,
                subscription_tier=SubscriptionTier.FREE,
                subscription_expires=datetime.now() + timedelta(days=30),
                daily_usage=0,
                total_summaries=0,
                created_at=datetime.now(),
                language=language
            )
            
            data = {
                'user_id': user.user_id,
                'username': user.username,
                'subscription_tier': user.subscription_tier.value,
                'subscription_expires': user.subscription_expires.isoformat(),
                'daily_usage': user.daily_usage,
                'total_summaries': user.total_summaries,
                'created_at': user.created_at.isoformat(),
                'language': user.language
            }
            
            self.supabase.table('users').insert(data).execute()
            return user
            
        except Exception as e:
            logger.error(f"Error creating user {user_id}: {e}")
            raise
    
    async def update_user(self, user: User) -> bool:
        """Update user information"""
        try:
            data = asdict(user)
            data['subscription_tier'] = user.subscription_tier.value
            data['subscription_expires'] = user.subscription_expires.isoformat()
            data['created_at'] = user.created_at.isoformat()
            if user.last_payment:
                data['last_payment'] = user.last_payment.isoformat()
            
            self.supabase.table('users').update(data).eq('user_id', user.user_id).execute()
            return True
            
        except Exception as e:
            logger.error(f"Error updating user {user.user_id}: {e}")
            return False
    
    async def update_user_language(self, user_id: str, language: str) -> bool:
        """Update user language preference"""
        try:
            self.supabase.table('users').update({'language': language}).eq('user_id', user_id).execute()
            return True
            
        except Exception as e:
            logger.error(f"Error updating user language {user_id}: {e}")
            return False
    
    async def save_video_summary(self, summary: VideoSummary) -> bool:
        """Save video summary to database"""
        try:
            data = asdict(summary)
            data['status'] = summary.status.value
            data['created_at'] = summary.created_at.isoformat()
            
            self.supabase.table('video_summaries').insert(data).execute()
            return True
            
        except Exception as e:
            logger.error(f"Error saving video summary: {e}")
            return False
    
    async def get_user_summaries(self, user_id: str, limit: int = 10) -> List[VideoSummary]:
        """Get user's recent summaries"""
        try:
            result = self.supabase.table('video_summaries').select('*').eq('user_id', user_id).order('created_at', desc=True).limit(limit).execute()
            
            summaries = []
            for row in result.data:
                summary = VideoSummary(
                    id=row['id'],
                    user_id=row['user_id'],
                    youtube_url=row['youtube_url'],
                    video_id=row['video_id'],
                    title=row['title'],
                    duration=row['duration'],
                    transcript=row['transcript'],
                    summary_short=row['summary_short'],
                    summary_medium=row['summary_medium'],
                    summary_detailed=row['summary_detailed'],
                    language=row['language'],
                    status=ProcessingStatus(row['status']),
                    created_at=datetime.fromisoformat(row['created_at']),
                    file_path=row.get('file_path')
                )
                summaries.append(summary)
            
            return summaries
            
        except Exception as e:
            logger.error(f"Error getting user summaries: {e}")
            return []
    
    async def reset_daily_usage(self):
        """Reset daily usage for all users"""
        try:
            self.supabase.table('users').update({'daily_usage': 0}).neq('user_id', 0).execute()
            
        except Exception as e:
            logger.error(f"Error resetting daily usage: {e}")

# Singleton instance for shared access
_database_manager = None

def get_database() -> DatabaseManager:
    """Get shared database manager instance"""
    global _database_manager
    if _database_manager is None:
        _database_manager = DatabaseManager()
    return _database_manager