# Этот файл содержит вспомогательные функции для использования в разных сервисах

# shared/utils/helpers.py
import os
import re
import hashlib
import uuid
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, parse_qs

def generate_task_id() -> str:
    """Generate unique task ID"""
    return str(uuid.uuid4())

def generate_summary_id(user_id: str, video_id: str) -> str:
    """Generate unique summary ID"""
    timestamp = datetime.now().isoformat()
    return hashlib.md5(f"{user_id}_{video_id}_{timestamp}".encode()).hexdigest()

def extract_youtube_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from URL"""
    try:
        parsed_url = urlparse(url)
        
        if parsed_url.hostname in ['www.youtube.com', 'youtube.com']:
            if parsed_url.path == '/watch':
                return parse_qs(parsed_url.query)['v'][0]
            elif parsed_url.path.startswith('/embed/'):
                return parsed_url.path.split('/')[2]
        elif parsed_url.hostname == 'youtu.be':
            return parsed_url.path[1:]
        
        return None
        
    except Exception:
        return None

def is_youtube_url(url: str) -> bool:
    """Check if URL is a valid YouTube URL"""
    youtube_pattern = re.compile(
        r'(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)[A-Za-z0-9_-]{11}'
    )
    return bool(youtube_pattern.search(url))

def format_duration(seconds: int) -> str:
    """Format duration in seconds to MM:SS format"""
    minutes = seconds // 60
    seconds = seconds % 60
    return f"{minutes}:{seconds:02d}"

def format_file_size(size_bytes: int) -> str:
    """Format file size in bytes to human readable format"""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024
        i += 1
    
    return f"{size_bytes:.1f} {size_names[i]}"

def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe storage"""
    # Remove invalid characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Limit length
    if len(sanitized) > 100:
        sanitized = sanitized[:100]
    return sanitized

def get_file_extension(mime_type: str) -> str:
    """Get file extension from MIME type"""
    mime_to_ext = {
        'audio/mp3': '.mp3',
        'audio/mpeg': '.mp3',
        'audio/wav': '.wav',
        'audio/wave': '.wav',
        'audio/x-wav': '.wav',
        'audio/m4a': '.m4a',
        'audio/mp4': '.m4a',
        'audio/ogg': '.ogg',
        'video/mp4': '.mp4',
        'video/avi': '.avi',
        'video/mov': '.mov',
        'video/quicktime': '.mov'
    }
    return mime_to_ext.get(mime_type, '.bin')

def create_temp_filename(prefix: str, extension: str) -> str:
    """Create temporary filename with timestamp"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return f"{prefix}_{timestamp}{extension}"

def ensure_directory_exists(path: str) -> bool:
    """Ensure directory exists, create if not"""
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except Exception:
        return False

def chunk_text(text: str, max_length: int = 4000) -> list:
    """Split text into chunks of maximum length"""
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    current_chunk = ""
    
    # Split by sentences first
    sentences = text.split('. ')
    
    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 2 <= max_length:
            current_chunk += sentence + '. '
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence + '. '
    
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks

def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate text to maximum length with suffix"""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix

def validate_language_code(lang_code: str) -> bool:
    """Validate language code"""
    valid_codes = ['en', 'ru', 'es', 'fr', 'de', 'it', 'pt', 'ja', 'ko', 'zh']
    return lang_code in valid_codes

def get_priority_from_subscription(subscription_tier: str) -> int:
    """Get task priority based on subscription tier"""
    priority_map = {
        'free': 1,
        'premium': 3,
        'enterprise': 5
    }
    return priority_map.get(subscription_tier.lower(), 1)