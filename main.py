import os
import asyncio
import logging
import re
import json
import tempfile
import shutil
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import hashlib
from urllib.parse import urlparse, parse_qs

# External libraries
from telethon import TelegramClient, events, Button
from telethon.tl.types import Message, MessageMediaDocument
from supabase import create_client, Client
import google.generativeai as genai
from dotenv import load_dotenv
import requests
from youtube_transcript_api import YouTubeTranscriptApi
from pytube import YouTube
import tiktoken
import stripe

import torch
import whisper
import yt_dlp
from pydub import AudioSegment

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('youtube_summarizer.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SubscriptionTier(Enum):
    FREE = "free"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"

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
class User:
    user_id: int
    username: str
    subscription_tier: SubscriptionTier
    subscription_expires: datetime
    daily_usage: int
    total_summaries: int
    created_at: datetime
    last_payment: Optional[datetime] = None

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
    subscription_tier: SubscriptionTier
    stripe_session_id: str
    status: str
    created_at: datetime

class UsageLimits:
    """Usage limits for different subscription tiers"""
    
    LIMITS = {
        SubscriptionTier.FREE: {
            'daily_summaries': 5,
            'max_video_duration': 1800,  # 30 minutes
            'summary_types': [SummaryType.SHORT],
            'priority_processing': False
        },
        SubscriptionTier.PREMIUM: {
            'daily_summaries': 50,
            'max_video_duration': 7200,  # 2 hours
            'summary_types': [SummaryType.SHORT, SummaryType.MEDIUM, SummaryType.DETAILED],
            'priority_processing': True
        },
        SubscriptionTier.ENTERPRISE: {
            'daily_summaries': -1,  # Unlimited
            'max_video_duration': -1,  # Unlimited
            'summary_types': [SummaryType.SHORT, SummaryType.MEDIUM, SummaryType.DETAILED],
            'priority_processing': True
        }
    }

class YouTubeProcessor:
    """Handles YouTube video processing and transcript extraction"""
    
    def __init__(self):
        self.encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")
        self.audio_processor = AudioProcessor()  
    
    def extract_video_id(self, url: str) -> Optional[str]:
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
            
        except Exception as e:
            logger.error(f"Error extracting video ID from {url}: {e}")
            return None
    
    async def get_video_info(self, video_id: str) -> Optional[Dict]:
        """Get video information with fallback"""
        try:
            # Try pytube first
            yt = YouTube(f"https://www.youtube.com/watch?v={video_id}")
            return {
                'title': yt.title,
                'duration': yt.length,
                'author': yt.author,
                'description': yt.description,
                'publish_date': yt.publish_date,
                'views': yt.views
            }
        except Exception as e:
            logger.warning(f"Pytube failed for {video_id}: {e}")
            
            # Fallback - basic info
            try:
                # Try with yt-dlp for basic info
                import yt_dlp
                ydl_opts = {'quiet': True, 'no_warnings': True}
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                    
                    return {
                        'title': info.get('title', f'YouTube Video {video_id}'),
                        'duration': info.get('duration', 0),
                        'author': info.get('uploader', 'Unknown'),
                        'description': info.get('description', ''),
                        'publish_date': None,
                        'views': info.get('view_count', 0)
                    }
            except Exception as e2:
                logger.error(f"Both pytube and yt-dlp failed for {video_id}: {e2}")
                
                # Final fallback - minimal info
                return {
                    'title': f'YouTube Video {video_id}',
                    'duration': 0,
                    'author': 'Unknown',
                    'description': '',
                    'publish_date': None,
                    'views': 0
                }
    
    async def get_transcript(self, video_id: str) -> Optional[Tuple[str, str]]:
        """Get transcript - try YouTube API first, fallback to Whisper"""
        try:
            # Try YouTube Transcript API first (FAST)
            logger.info(f"Trying YouTube Transcript API for {video_id}")
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            # Try preferred languages
            languages = ['en', 'en-US', 'en-GB', 'ru']
            transcript = None
            language = 'en'
            
            for lang in languages:
                try:
                    transcript = transcript_list.find_transcript([lang])
                    language = lang
                    logger.info(f"Found {lang} transcript via API")
                    break
                except Exception as lang_error:
                    logger.debug(f"Language {lang} not found: {lang_error}")
                    continue
            
            # If no preferred language, get any available
            if not transcript:
                try:
                    # Get first available transcript
                    all_transcripts = list(transcript_list)
                    if all_transcripts:
                        transcript = all_transcripts[0]
                        language = transcript.language_code
                        logger.info(f"Found {language} transcript via API")
                except Exception as e:
                    logger.debug(f"No transcripts available: {e}")
            
            if transcript:
                try:
                    transcript_data = transcript.fetch()
                    full_transcript = ' '.join([item['text'] for item in transcript_data])
                    
                    if len(full_transcript.strip()) > 10:  # Valid transcript
                        logger.info(f"✅ YouTube API transcript: {len(full_transcript)} chars")
                        return full_transcript, language
                    else:
                        logger.warning("Empty or too short transcript from API")
                        
                except Exception as fetch_error:
                    logger.warning(f"Error fetching transcript data: {fetch_error}")
                
        except Exception as e:
            logger.warning(f"YouTube Transcript API failed for {video_id}: {e}")
        
        # FALLBACK: Use Whisper to extract from audio
        logger.info(f"Falling back to Whisper for {video_id}")
        try:
            return await self.get_transcript_with_whisper(video_id)
        except Exception as e:
            logger.error(f"Whisper also failed for {video_id}: {e}")
            return None, None

    async def get_transcript_with_whisper(self, video_id: str) -> Optional[Tuple[str, str]]:
        """Extract transcript using Whisper (when no subtitles available)"""
        try:
            # Load Whisper model if not loaded
            if not hasattr(self, 'whisper_model') or self.whisper_model is None:
                logger.info("Loading Whisper model...")
                import whisper
                device = "cuda" if torch.cuda.is_available() else "cpu"
                self.whisper_model = whisper.load_model("base", device=device)
            
            # Download audio from YouTube
            audio_path = await self.download_youtube_audio(video_id)
            if not audio_path:
                logger.error(f"Failed to download audio for {video_id}")
                return None, None
            
            # Transcribe with Whisper
            logger.info(f"Transcribing {video_id} with Whisper...")
            result = self.whisper_model.transcribe(audio_path)
            
            # Cleanup
            try:
                os.remove(audio_path)
            except:
                pass
            
            logger.info(f"✅ Whisper transcript: {len(result['text'])} chars")
            return result["text"], result["language"]
            
        except Exception as e:
            logger.error(f"Whisper transcription failed for {video_id}: {e}")
            return None, None

    async def download_youtube_audio(self, video_id: str) -> Optional[str]:
        """Download audio from YouTube video"""
        try:
            import yt_dlp
            
            url = f"https://www.youtube.com/watch?v={video_id}"
            
            # yt-dlp options for audio only
            ydl_opts = {
                'format': 'bestaudio[ext=m4a]/bestaudio/best',
                'outtmpl': f'temp_audio_{video_id}.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'wav',
                    'preferredquality': '192',
                }],
                'postprocessor_args': [
                    '-ar', '16000'  # Whisper preferred sample rate
                ],
                'quiet': True,
                'no_warnings': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            audio_file = f'temp_audio_{video_id}.wav'
            if os.path.exists(audio_file):
                logger.info(f"✅ Downloaded audio: {audio_file}")
                return audio_file
            
            return None
            
        except Exception as e:
            logger.error(f"Error downloading YouTube audio for {video_id}: {e}")
            return None
    
    def chunk_transcript(self, transcript: str, max_tokens: int = 4000) -> List[str]:
        """Split transcript into chunks for processing"""
        tokens = self.encoding.encode(transcript)
        chunks = []
        
        for i in range(0, len(tokens), max_tokens):
            chunk_tokens = tokens[i:i + max_tokens]
            chunk_text = self.encoding.decode(chunk_tokens)
            chunks.append(chunk_text)
        
        return chunks

class AIProcessor:
    """Handles AI processing with Gemini and Ollama"""
    
    def __init__(self):
        # Initialize Gemini
        genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
        self.gemini_model = genai.GenerativeModel('gemini-2.0-flash-exp')
        
        # Ollama endpoint
        self.ollama_endpoint = os.getenv('OLLAMA_ENDPOINT', 'http://localhost:11434')
    
    async def generate_summary(self, transcript: str, summary_type: SummaryType, title: str, language: str = 'en') -> str:
        """Generate summary using Gemini with fallback to Ollama"""
        try:
            # Try Gemini first
            summary = await self._generate_with_gemini(transcript, summary_type, title, language)
            if summary:
                return summary
        except Exception as e:
            logger.error(f"Gemini failed: {e}")
        
        # Fallback to Ollama
        try:
            summary = await self._generate_with_ollama(transcript, summary_type, title, language)
            if summary:
                return summary
        except Exception as e:
            logger.error(f"Ollama failed: {e}")
        
        return "Unable to generate summary due to AI service unavailability."
    
    async def _generate_with_gemini(self, transcript: str, summary_type: SummaryType, title: str, language: str) -> str:
        """Generate summary using Gemini API"""
        prompts = {
            SummaryType.SHORT: f"""
            Create a concise summary of this YouTube video transcript in 2-3 sentences.
            
            Video Title: {title}
            Language: {language}
            
            Transcript:
            {transcript}
            
            Summary:
            """,
            
            SummaryType.MEDIUM: f"""
            Create a comprehensive summary of this YouTube video transcript in 1-2 paragraphs.
            Include key points, main topics, and important details.
            
            Video Title: {title}
            Language: {language}
            
            Transcript:
            {transcript}
            
            Summary:
            """,
            
            SummaryType.DETAILED: f"""
            Create a detailed analysis of this YouTube video transcript.
            Include:
            - Main topics and themes
            - Key points and arguments
            - Important quotes or statements
            - Conclusion or takeaways
            - Timestamp references if applicable
            
            Video Title: {title}
            Language: {language}
            
            Transcript:
            {transcript}
            
            Detailed Analysis:
            """
        }
        
        response = await asyncio.to_thread(
            self.gemini_model.generate_content,
            prompts[summary_type]
        )
        
        return response.text
    
    async def _generate_with_ollama(self, transcript: str, summary_type: SummaryType, title: str, language: str) -> str:
        """Generate summary using Ollama API"""
        prompts = {
            SummaryType.SHORT: f"Summarize this YouTube video '{title}' in 2-3 sentences:\n\n{transcript}",
            SummaryType.MEDIUM: f"Create a comprehensive summary of this YouTube video '{title}' in 1-2 paragraphs:\n\n{transcript}",
            SummaryType.DETAILED: f"Create a detailed analysis of this YouTube video '{title}' with key points, themes, and takeaways:\n\n{transcript}"
        }
        
        payload = {
            "model": "llama3.1",
            "prompt": prompts[summary_type],
            "stream": False
        }
        
        response = requests.post(f"{self.ollama_endpoint}/api/generate", json=payload)
        
        if response.status_code == 200:
            return response.json()['response']
        else:
            raise Exception(f"Ollama API error: {response.status_code}")

class AudioProcessor:
    """Process audio files with Whisper"""
    
    def __init__(self):
        self.whisper_models = {
            'tiny': None,
            'base': None,
            'small': None,
            'medium': None,
            'large': None,
            'large-v3': None
        }
        self.current_model_name = 'base'
        self.current_model = None
    
    def load_whisper_model(self, model_name: str = 'base'):
        """Load Whisper model"""
        try:
            if model_name not in self.whisper_models:
                model_name = 'base'
            
            if self.whisper_models[model_name] is None:
                logger.info(f"Loading Whisper model: {model_name}")
                import whisper
                device = "cuda" if torch.cuda.is_available() else "cpu"
                self.whisper_models[model_name] = whisper.load_model(model_name, device=device)
            
            self.current_model = self.whisper_models[model_name]
            self.current_model_name = model_name
            return True
            
        except Exception as e:
            logger.error(f"Error loading Whisper model {model_name}: {e}")
            return False
    
    async def transcribe_audio(self, audio_path: str) -> Optional[Tuple[str, str, int]]:
        """Transcribe audio file"""
        try:
            if not self.current_model:
                self.load_whisper_model('base')
            
            logger.info(f"Transcribing with Whisper model: {self.current_model_name}")
            
            # Get audio duration
            from pydub import AudioSegment
            audio = AudioSegment.from_file(audio_path)
            duration = len(audio) // 1000  # Convert to seconds
            
            # Transcribe
            result = self.current_model.transcribe(audio_path)
            
            return result["text"], result["language"], duration
            
        except Exception as e:
            logger.error(f"Error transcribing audio: {e}")
            return None, None, 0

class DatabaseManager:
    """Handles all database operations with Supabase"""
    
    def __init__(self):
        self.supabase: Client = create_client(
            os.getenv('SUPABASE_URL'),
            os.getenv('SUPABASE_KEY')
        )
    
    async def get_user(self, user_id: int) -> Optional[User]:
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
                    last_payment=datetime.fromisoformat(row['last_payment']) if row['last_payment'] else None
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None
    
    async def create_user(self, user_id: int, username: str) -> User:
        """Create new user"""
        try:
            user = User(
                user_id=user_id,
                username=username,
                subscription_tier=SubscriptionTier.FREE,
                subscription_expires=datetime.now() + timedelta(days=30),
                daily_usage=0,
                total_summaries=0,
                created_at=datetime.now()
            )
            
            data = {
            'user_id': user.user_id,
            'username': user.username,
            'subscription_tier': user.subscription_tier.value,
            'subscription_expires': user.subscription_expires.isoformat(),
            'daily_usage': user.daily_usage,
            'total_summaries': user.total_summaries,
            'created_at': user.created_at.isoformat()
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
    
    async def save_video_summary(self, summary: VideoSummary) -> bool:
        """Save video summary to database"""
        try:
            data = asdict(summary)
            data['subscription_tier'] = summary.subscription_tier.value if hasattr(summary, 'subscription_tier') else None
            data['status'] = summary.status.value
            data['created_at'] = summary.created_at.isoformat()
            
            self.supabase.table('video_summaries').insert(data).execute()
            return True
            
        except Exception as e:
            logger.error(f"Error saving video summary: {e}")
            return False
    
    async def get_user_summaries(self, user_id: int, limit: int = 10) -> List[VideoSummary]:
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

class PaymentManager:
    """Handles payment processing with Stripe"""
    
    def __init__(self):
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        self.webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
        
        self.prices = {
            SubscriptionTier.PREMIUM: {
                'monthly': os.getenv('STRIPE_PREMIUM_MONTHLY_PRICE_ID'),
                'yearly': os.getenv('STRIPE_PREMIUM_YEARLY_PRICE_ID')
            },
            SubscriptionTier.ENTERPRISE: {
                'monthly': os.getenv('STRIPE_ENTERPRISE_MONTHLY_PRICE_ID'),
                'yearly': os.getenv('STRIPE_ENTERPRISE_YEARLY_PRICE_ID')
            }
        }
    
    async def create_checkout_session(self, user_id: int, subscription_tier: SubscriptionTier, billing_period: str) -> str:
        """Create Stripe checkout session"""
        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price': self.prices[subscription_tier][billing_period],
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=f"{os.getenv('DOMAIN')}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{os.getenv('DOMAIN')}/payment/cancel",
                client_reference_id=str(user_id),
                metadata={
                    'user_id': str(user_id),
                    'subscription_tier': subscription_tier.value,
                    'billing_period': billing_period
                }
            )
            
            return session.url
            
        except Exception as e:
            logger.error(f"Error creating checkout session: {e}")
            raise
    
    async def handle_webhook(self, payload: str, sig_header: str) -> bool:
        """Handle Stripe webhook events"""
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, self.webhook_secret
            )
            
            if event['type'] == 'checkout.session.completed':
                session = event['data']['object']
                await self._handle_successful_payment(session)
            
            return True
            
        except Exception as e:
            logger.error(f"Error handling webhook: {e}")
            return False
    
    async def _handle_successful_payment(self, session):
        """Handle successful payment"""
        try:
            user_id = int(session['metadata']['user_id'])
            subscription_tier = SubscriptionTier(session['metadata']['subscription_tier'])
            billing_period = session['metadata']['billing_period']
            
            # Update user subscription
            # This would typically involve updating the user's subscription in the database
            logger.info(f"Payment successful for user {user_id}: {subscription_tier.value} ({billing_period})")
            
        except Exception as e:
            logger.error(f"Error handling successful payment: {e}")

class FileManager:
    """Handles file operations for transcripts and summaries"""
    
    def __init__(self):
        self.storage_dir = os.getenv('STORAGE_DIR', './files')
        os.makedirs(self.storage_dir, exist_ok=True)
    
    async def save_transcript(self, video_id: str, transcript: str) -> str:
        """Save transcript to file"""
        try:
            filename = f"transcript_{video_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            filepath = os.path.join(self.storage_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(transcript)
            
            return filepath
            
        except Exception as e:
            logger.error(f"Error saving transcript: {e}")
            raise
    
    async def save_summary(self, video_id: str, summary: str, summary_type: SummaryType) -> str:
        """Save summary to file"""
        try:
            filename = f"summary_{summary_type.value}_{video_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            filepath = os.path.join(self.storage_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(summary)
            
            return filepath
            
        except Exception as e:
            logger.error(f"Error saving summary: {e}")
            raise
    
    async def create_combined_file(self, video_summary: VideoSummary) -> str:
        """Create combined file with transcript and all summaries"""
        try:
            filename = f"complete_{video_summary.video_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            filepath = os.path.join(self.storage_dir, filename)
            
            content = f"""YouTube Video Summary Report
=================================

Title: {video_summary.title}
URL: {video_summary.youtube_url}
Duration: {video_summary.duration} seconds
Language: {video_summary.language}
Generated: {video_summary.created_at}

SHORT SUMMARY:
{video_summary.summary_short}

MEDIUM SUMMARY:
{video_summary.summary_medium}

DETAILED ANALYSIS:
{video_summary.summary_detailed}

FULL TRANSCRIPT:
{video_summary.transcript}
"""
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            return filepath
            
        except Exception as e:
            logger.error(f"Error creating combined file: {e}")
            raise

class YouTubeSummarizerBot:
    """Main bot application"""
    
    def __init__(self):
        # Initialize components
        self.client = TelegramClient(
            'youtube_summarizer',
            int(os.getenv('TELEGRAM_API_ID')),
            os.getenv('TELEGRAM_API_HASH')
        )
        
        self.youtube_processor = YouTubeProcessor()
        self.ai_processor = AIProcessor()
        self.db_manager = DatabaseManager()
        self.file_manager = FileManager()
        
        # Processing queue
        self.processing_queue = asyncio.Queue()
        self.processing_workers = []
        
        # URL validation pattern
        self.youtube_url_pattern = re.compile(
            r'(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)[A-Za-z0-9_-]{11}'
        )
    
    async def start(self):
        """Start the bot"""
        logger.info("Starting YouTube Summarizer Bot...")
        
        # Start the client
        await self.client.start(bot_token=os.getenv('TELEGRAM_BOT_TOKEN'))
        
        # Test database connection
        if not await self.test_database_connection():
            logger.error("Database connection failed!")
            return
        
        # Set up event handlers
        @self.client.on(events.NewMessage(pattern='/start'))
        async def handle_start(event):
            await self.handle_start_command(event)

        @self.client.on(events.NewMessage(pattern='/help'))
        async def handle_help(event):
            await self.handle_help_command(event)
            
        @self.client.on(events.NewMessage(pattern='/status'))
        async def handle_status(event):
            await self.handle_status_command(event)
            
        @self.client.on(events.NewMessage(pattern='/history'))
        async def handle_history(event):
            await self.handle_history_command(event)

        @self.client.on(events.NewMessage())
        async def handle_message(event):
            await self.handle_any_message(event)
        
        # Start processing workers
        for i in range(3):  # 3 concurrent workers
            worker = asyncio.create_task(self.process_queue_worker())
            self.processing_workers.append(worker)
        
        # Start daily reset task
        asyncio.create_task(self.daily_reset_task())
        
        logger.info("Bot started successfully!")
        await self.client.run_until_disconnected()
    
    async def test_database_connection(self):
        """Test database connection and permissions"""
        try:
            # Test read
            result = self.db_manager.supabase.table('users').select('count').limit(1).execute()
            logger.info("✅ Database read test: SUCCESS")
            
            # Test write with temp user
            test_user_data = {
                'user_id': 999999999,
                'username': 'test_user',
                'subscription_tier': 'free',
                'subscription_expires': datetime.now().isoformat(),
                'daily_usage': 0,
                'total_summaries': 0,
                'created_at': datetime.now().isoformat()
            }
            
            # Delete if exists
            self.db_manager.supabase.table('users').delete().eq('user_id', 999999999).execute()
            
            # Create new
            result = self.db_manager.supabase.table('users').insert(test_user_data).execute()
            logger.info("✅ Database write test: SUCCESS")
            
            # Delete test user
            self.db_manager.supabase.table('users').delete().eq('user_id', 999999999).execute()
            logger.info("✅ Database delete test: SUCCESS")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Database test failed: {e}")
            return False
    
    async def handle_start_command(self, event):
        """Handle /start command"""
        try:
            user_id = event.sender_id
            username = event.sender.username or f"user_{user_id}"
            
            # Get or create user
            user = await self.db_manager.get_user(user_id)
            if not user:
                user = await self.db_manager.create_user(user_id, username)

            welcome_msg = f"""🎥 **YouTube Summarizer Bot - БЕТА ТЕСТ!**

Привет {username}! Все функции временно бесплатны! 🚀

**Что умею:**
• 📹 YouTube видео → краткое содержание
• 🎵 Голосовые сообщения → текст  
• 🎧 Аудио файлы → краткое содержание

**Просто отправьте:**
- Ссылку на YouTube
- Голосовое сообщение
- Аудио файл

**Команды:**
/help - Справка
/status - Статус
/history - История

Отправьте YouTube ссылку для начала! 🎯"""
            
            await event.reply(welcome_msg)
            
        except Exception as e:
            logger.error(f"Error in start command: {e}")
            await event.reply("❌ Произошла ошибка. Попробуйте снова.")
    
    async def handle_help_command(self, event):
        """Handle /help command"""
        help_msg = """📖 **Справка по YouTube Summarizer Bot**

**Команды:**
/start - Приветствие и настройка
/help - Эта справка
/status - Статус аккаунта
/history - История обработки

**Поддерживаемые форматы:**
• YouTube URLs (любые ссылки)
• Голосовые сообщения Telegram
• Аудио файлы (MP3, WAV, M4A, OGG)
• Видео файлы (MP4, AVI, MOV)

**Как использовать:**
1. Отправьте YouTube ссылку
2. Запишите голосовое сообщение
3. Загрузите аудио/видео файл

**Функции:**
✅ Извлечение транскрипта
✅ Краткое содержание
✅ Сохранение файлов
✅ История обработки

Бот находится в режиме бета-тестирования! 🚀"""
        
        await event.reply(help_msg)
    
    async def handle_status_command(self, event):
        """Handle /status command"""
        try:
            user_id = event.sender_id
            user = await self.db_manager.get_user(user_id)
            
            if not user:
                await event.reply("❌ Пользователь не найден. Используйте /start")
                return

            status_msg = f"""📊 **Ваш статус**

**Режим:** БЕТА-ТЕСТ (все бесплатно!)
**Пользователь:** {user.username}
**Обработано сегодня:** {user.daily_usage}
**Всего обработано:** {user.total_summaries}

**Доступные функции:**
✅ YouTube видео (без ограничений)
✅ Голосовые сообщения
✅ Аудио файлы
✅ Видео файлы

**Аккаунт создан:** {user.created_at.strftime('%Y-%m-%d')}

Наслаждайтесь бесплатным использованием! 🎉"""
            
            await event.reply(status_msg)
            
        except Exception as e:
            logger.error(f"Error in status command: {e}")
            await event.reply("❌ Ошибка получения статуса.")
    
    async def handle_history_command(self, event):
        """Handle /history command"""
        try:
            user_id = event.sender_id
            summaries = await self.db_manager.get_user_summaries(user_id, 10)
            
            if not summaries:
                await event.reply("📝 История пуста. Отправьте YouTube ссылку для начала!")
                return
            
            history_msg = "📚 **Ваша история (последние 10)**\n\n"
            
            for i, summary in enumerate(summaries, 1):
                status_emoji = {
                    ProcessingStatus.COMPLETED: "✅",
                    ProcessingStatus.PROCESSING: "⏳",
                    ProcessingStatus.FAILED: "❌",
                    ProcessingStatus.PENDING: "⏳"
                }
                
                title = summary.title[:40] + "..." if len(summary.title) > 40 else summary.title
                history_msg += f"{i}. {status_emoji[summary.status]} **{title}**\n"
                history_msg += f"   🕒 {summary.created_at.strftime('%d.%m.%Y %H:%M')}\n"
                if summary.youtube_url:
                    history_msg += f"   🔗 [Ссылка на видео]({summary.youtube_url})\n"
                history_msg += "\n"
            
            await event.reply(history_msg, parse_mode='markdown')
            
        except Exception as e:
            logger.error(f"Error in history command: {e}")
            await event.reply("❌ Ошибка получения истории.")
    
    async def handle_any_message(self, event):
        """Handle all other messages"""
        try:
            # Skip commands
            if event.message.text and event.message.text.startswith('/'):
                return
            
            # YouTube URLs
            if event.message.text and self.youtube_url_pattern.search(event.message.text):
                await self.handle_youtube_url(event)
                return
            
            # Voice messages
            if event.message.voice:
                await self.handle_voice_message(event)
                return
            
            # Documents (audio files)
            if event.message.document:
                doc = event.message.document
                if doc.mime_type and doc.mime_type.startswith('audio/'):
                    await self.handle_audio_file(event)
                    return
                else:
                    await event.reply("🎧 Поддерживаются только аудио файлы (MP3, WAV, M4A, OGG)")
                    return
            
            # Default response
            await event.reply("""Отправьте:
    - 📹 YouTube ссылку
    - 🎵 Голосовое сообщение  
    - 🎧 Аудио файл (MP3, WAV, M4A)

    Команды: /help /status /history /whisper""")
            
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def handle_voice_message(self, event):
        """Handle voice messages from Telegram"""
        try:
            user_id = event.sender_id
            user = await self.db_manager.get_user(user_id)
            
            if not user:
                await event.reply("❌ Используйте /start для настройки аккаунта.")
                return
            
            # Send processing message
            processing_msg = await event.reply("🎵 **Обрабатываю голосовое сообщение...**\n\nИзвлекаю аудио...")
            
            # Download voice message
            voice_file = await self.download_voice_message(event.message)
            if not voice_file:
                await processing_msg.edit("❌ Ошибка скачивания голосового сообщения.")
                return
            
            # Add to processing queue
            task_data = {
                'user_id': user_id,
                'user': user,
                'content_type': 'voice_message',
                'file_path': voice_file,
                'title': f"Голосовое сообщение от {user.username}",
                'message_id': processing_msg.id,
                'chat_id': event.chat_id
            }
            
            await self.processing_queue.put(task_data)
            
        except Exception as e:
            logger.error(f"Error handling voice message: {e}")
            await event.reply("❌ Ошибка обработки голосового сообщения.")

    async def download_voice_message(self, message) -> Optional[str]:
        """Download voice message from Telegram"""
        try:
            # Create temp directory
            temp_dir = tempfile.mkdtemp()
            
            # Download file
            file_path = await self.client.download_media(
                message.voice,
                file=temp_dir
            )
            
            if file_path:
                # Convert to WAV for Whisper
                wav_path = file_path.replace('.oga', '.wav').replace('.ogg', '.wav')
                
                # Convert using pydub
                from pydub import AudioSegment
                audio = AudioSegment.from_file(file_path)
                audio = audio.set_frame_rate(16000)  # Whisper preferred
                audio.export(wav_path, format="wav")
                
                # Remove original
                if os.path.exists(file_path) and file_path != wav_path:
                    os.remove(file_path)
                
                return wav_path
            
            return None
            
        except Exception as e:
            logger.error(f"Error downloading voice message: {e}")
            return None
   
    async def handle_audio_file(self, event):
        """Handle audio files (MP3, WAV, M4A, etc.)"""
        try:
            user_id = event.sender_id
            user = await self.db_manager.get_user(user_id)
            
            if not user:
                await event.reply("❌ Используйте /start для настройки аккаунта.")
                return
            
            doc = event.message.document
            file_name = doc.attributes[0].file_name if doc.attributes else "audio_file"
            file_size_mb = doc.size / (1024 * 1024)
            
            # Check file size (limit 50MB for free users)
            if file_size_mb > 50:
                await event.reply(f"❌ Файл слишком большой ({file_size_mb:.1f} MB). Максимум 50 MB.")
                return
            
            # Send processing message
            processing_msg = await event.reply(
                f"🎧 **Обрабатываю аудио файл...**\n\n"
                f"**Файл:** {file_name}\n"
                f"**Размер:** {file_size_mb:.1f} MB\n\n"
                f"Скачиваю файл..."
            )
            
            # Download audio file
            audio_file = await self.download_audio_file(event.message, file_name)
            if not audio_file:
                await processing_msg.edit("❌ Ошибка скачивания аудио файла.")
                return
            
            # Add to processing queue
            task_data = {
                'user_id': user_id,
                'user': user,
                'content_type': 'audio_file',
                'file_path': audio_file,
                'title': file_name,
                'message_id': processing_msg.id,
                'chat_id': event.chat_id
            }
            
            await self.processing_queue.put(task_data)
            
        except Exception as e:
            logger.error(f"Error handling audio file: {e}")
            await event.reply("❌ Ошибка обработки аудио файла.")

    async def download_audio_file(self, message, file_name: str) -> Optional[str]:
        """Download audio file from Telegram"""
        try:
            # Create temp directory
            temp_dir = tempfile.mkdtemp()
            
            # Download file
            file_path = await self.client.download_media(
                message.document,
                file=os.path.join(temp_dir, file_name)
            )
            
            if file_path:
                # Convert to WAV for Whisper if needed
                if not file_path.endswith('.wav'):
                    wav_path = file_path.rsplit('.', 1)[0] + '.wav'
                    
                    from pydub import AudioSegment
                    audio = AudioSegment.from_file(file_path)
                    audio = audio.set_frame_rate(16000)
                    audio.export(wav_path, format="wav")
                    
                    # Remove original if different
                    if file_path != wav_path:
                        os.remove(file_path)
                    
                    return wav_path
                
                return file_path
            
            return None
            
        except Exception as e:
            logger.error(f"Error downloading audio file: {e}")
            return None

    async def handle_youtube_url(self, event):
        """Handle YouTube URL messages"""
        try:
            message_text = event.message.text
            user_id = event.sender_id
            user = await self.db_manager.get_user(user_id)
            
            if not user:
                await event.reply("❌ Используйте /start для настройки аккаунта.")
                return
            
            # Extract video ID
            video_id = self.youtube_processor.extract_video_id(message_text)
            if not video_id:
                await event.reply("❌ Неверная YouTube ссылка. Проверьте URL.")
                return
            
            # Get video info
            video_info = await self.youtube_processor.get_video_info(video_id)
            if not video_info:
                await event.reply("❌ Не удалось получить информацию о видео. Возможно, оно приватное или удалено.")
                return
            
            # Send processing message
            processing_msg = await event.reply(
                f"⏳ **Обрабатываю видео...**\n\n"
                f"**Название:** {video_info['title']}\n"
                f"**Длительность:** {video_info['duration']//60}:{video_info['duration']%60:02d}\n\n"
                f"Это может занять несколько минут..."
            )
            
            # Add to processing queue
            task_data = {
                'user_id': user_id,
                'user': user,
                'video_id': video_id,
                'youtube_url': message_text,
                'video_info': video_info,
                'message_id': processing_msg.id,
                'chat_id': event.chat_id
            }
            
            await self.processing_queue.put(task_data)
            
        except Exception as e:
            logger.error(f"Error handling YouTube URL: {e}")
            await event.reply("❌ Произошла ошибка при обработке ссылки.")
    
    async def process_queue_worker(self):
        """Worker to process video summarization tasks"""
        while True:
            try:
                # Get task from queue
                task_data = await self.processing_queue.get()
                
                user_id = task_data['user_id']
                user = task_data['user']
                message_id = task_data['message_id']
                chat_id = task_data['chat_id']
                
                try:
                    # YouTube Video Processing
                    if task_data.get('content_type') == 'youtube_video' or 'video_id' in task_data:
                        video_id = task_data['video_id']
                        youtube_url = task_data['youtube_url']
                        video_info = task_data.get('video_info')
                        
                        # If no video_info, try to get basic info
                        if not video_info:
                            video_info = {
                                'title': f"YouTube Video {video_id}",
                                'duration': 0,
                                'author': 'Unknown'
                            }
                        
                        # Update processing message
                        await self.client.edit_message(
                            chat_id, message_id,
                            f"⏳ **Обрабатываю видео...**\n\n"
                            f"**Название:** {video_info['title']}\n"
                            f"**Статус:** Извлекаю транскрипт..."
                        )
                        
                        # Get transcript
                        transcript, language = await self.youtube_processor.get_transcript(video_id)
                        if not transcript:
                            await self.client.edit_message(
                                chat_id, message_id,
                                f"❌ **Обработка не удалась**\n\n"
                                f"**Название:** {video_info['title']}\n"
                                f"**Ошибка:** Не удалось извлечь транскрипт. Возможно, у видео нет субтитров."
                            )
                            continue
                        
                        # Update message
                        await self.client.edit_message(
                            chat_id, message_id,
                            f"⏳ **Обрабатываю видео...**\n\n"
                            f"**Название:** {video_info['title']}\n"
                            f"**Статус:** Генерирую краткое содержание..."
                        )
                        
                        # Generate summaries (all types for beta)
                        summaries = {}
                        for summary_type in [SummaryType.SHORT, SummaryType.MEDIUM, SummaryType.DETAILED]:
                            summary = await self.ai_processor.generate_summary(
                                transcript, summary_type, video_info['title'], language
                            )
                            summaries[summary_type] = summary
                        
                        # Save transcript to file
                        transcript_file = await self.file_manager.save_transcript(video_id, transcript)
                        
                        # Create video summary object
                        video_summary = VideoSummary(
                            id=hashlib.md5(f"{user_id}_{video_id}_{datetime.now()}".encode()).hexdigest(),
                            user_id=user_id,
                            youtube_url=youtube_url,
                            video_id=video_id,
                            title=video_info['title'],
                            duration=video_info.get('duration', 0),
                            transcript=transcript,
                            summary_short=summaries[SummaryType.SHORT],
                            summary_medium=summaries[SummaryType.MEDIUM],
                            summary_detailed=summaries[SummaryType.DETAILED],
                            language=language,
                            status=ProcessingStatus.COMPLETED,
                            created_at=datetime.now(),
                            file_path=transcript_file
                        )
                        
                        # Save to database
                        await self.db_manager.save_video_summary(video_summary)
                        
                        # Update user usage
                        user.daily_usage += 1
                        user.total_summaries += 1
                        await self.db_manager.update_user(user)
                        
                        # Create combined file
                        combined_file = await self.file_manager.create_combined_file(video_summary)
                        
                        # Send completion message
                        completion_msg = f"✅ **Обработка завершена!**\n\n"
                        completion_msg += f"**Название:** {video_info['title']}\n"
                        completion_msg += f"**Длительность:** {video_info.get('duration', 0)//60}:{video_info.get('duration', 0)%60:02d}\n"
                        completion_msg += f"**Язык:** {language}\n\n"
                        completion_msg += f"**📝 Краткое содержание:**\n{summaries[SummaryType.SHORT][:500]}{'...' if len(summaries[SummaryType.SHORT]) > 500 else ''}\n\n"
                        completion_msg += f"Полный отчет отправлен файлом ⬇️"
                        
                        await self.client.edit_message(chat_id, message_id, completion_msg)
                        
                        # Send combined file
                        await self.client.send_file(
                            chat_id,
                            combined_file,
                            caption=f"📁 Полный отчет: {video_info['title']}"
                        )
                    
                    # Audio Processing (Voice Messages & Audio Files)
                    elif task_data.get('content_type') in ['voice_message', 'audio_file']:
                        file_path = task_data['file_path']
                        title = task_data['title']
                        content_type = task_data['content_type']
                        
                        await self.client.edit_message(
                            chat_id, message_id,
                            f"🎤 **Обрабатываю аудио...**\n\n"
                            f"**Файл:** {title}\n"
                            f"**Статус:** Извлекаю текст из аудио..."
                        )
                        
                        # Transcribe audio
                        transcript, language, duration = await self.audio_processor.transcribe_audio(file_path)
                        
                        if not transcript:
                            await self.client.edit_message(
                                chat_id, message_id,
                                f"❌ **Обработка не удалась**\n\n"
                                f"**Файл:** {title}\n"
                                f"**Ошибка:** Не удалось извлечь текст из аудио."
                            )
                            # Cleanup
                            if os.path.exists(file_path):
                                shutil.rmtree(os.path.dirname(file_path), ignore_errors=True)
                            continue
                        
                        # Generate summary
                        await self.client.edit_message(
                            chat_id, message_id,
                            f"🎤 **Обрабатываю аудио...**\n\n"
                            f"**Файл:** {title}\n"
                            f"**Статус:** Генерирую краткое содержание..."
                        )
                        
                        # Generate summaries
                        summaries = {}
                        for summary_type in [SummaryType.SHORT, SummaryType.MEDIUM, SummaryType.DETAILED]:
                            summary = await self.ai_processor.generate_summary(
                                transcript, summary_type, title, language
                            )
                            summaries[summary_type] = summary
                        
                        # Save transcript to file
                        transcript_file = await self.file_manager.save_transcript(f"audio_{user_id}_{int(datetime.now().timestamp())}", transcript)
                        
                        # Create audio summary object (using VideoSummary structure)
                        audio_summary = VideoSummary(
                            id=hashlib.md5(f"{user_id}_audio_{datetime.now()}".encode()).hexdigest(),
                            user_id=user_id,
                            youtube_url=None,  # No URL for audio files
                            video_id=f"audio_{int(datetime.now().timestamp())}",
                            title=title,
                            duration=duration,
                            transcript=transcript,
                            summary_short=summaries[SummaryType.SHORT],
                            summary_medium=summaries[SummaryType.MEDIUM],
                            summary_detailed=summaries[SummaryType.DETAILED],
                            language=language,
                            status=ProcessingStatus.COMPLETED,
                            created_at=datetime.now(),
                            file_path=transcript_file
                        )
                        
                        # Save to database
                        await self.db_manager.save_video_summary(audio_summary)
                        
                        # Update user usage
                        user.daily_usage += 1
                        user.total_summaries += 1
                        await self.db_manager.update_user(user)
                        
                        # Create combined file
                        combined_file = await self.file_manager.create_combined_file(audio_summary)
                        
                        # Send completion message
                        emoji = "🎵" if content_type == "voice_message" else "🎧"
                        completion_msg = f"✅ **Обработка завершена!**\n\n"
                        completion_msg += f"{emoji} **{title}**\n"
                        completion_msg += f"**Длительность:** {duration//60}:{duration%60:02d}\n"
                        completion_msg += f"**Язык:** {language}\n\n"
                        completion_msg += f"**📝 Краткое содержание:**\n{summaries[SummaryType.SHORT][:500]}{'...' if len(summaries[SummaryType.SHORT]) > 500 else ''}\n\n"
                        completion_msg += f"Полный отчет отправлен файлом ⬇️"
                        
                        await self.client.edit_message(chat_id, message_id, completion_msg)
                        
                        # Send combined file
                        await self.client.send_file(
                            chat_id,
                            combined_file,
                            caption=f"📁 Полный отчет: {title}"
                        )
                        
                        # Cleanup audio file
                        if os.path.exists(file_path):
                            try:
                                shutil.rmtree(os.path.dirname(file_path), ignore_errors=True)
                            except:
                                try:
                                    os.remove(file_path)
                                except:
                                    pass
                    
                    logger.info(f"Successfully processed content for user {user_id}")
                    
                except Exception as process_error:
                    logger.error(f"Error processing task: {process_error}")
                    
                    try:
                        await self.client.edit_message(
                            chat_id, message_id,
                            f"❌ **Обработка не удалась**\n\n"
                            f"**Ошибка:** {str(process_error)[:200]}...\n\n"
                            f"Попробуйте еще раз или обратитесь в поддержку."
                        )
                    except:
                        pass
                
                # Mark task as done
                self.processing_queue.task_done()
                
            except Exception as worker_error:
                logger.error(f"Worker error: {worker_error}")
                await asyncio.sleep(5)
    
    async def daily_reset_task(self):
        """Reset daily usage counters at midnight"""
        while True:
            try:
                now = datetime.now()
                # Calculate time until next midnight
                tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                sleep_seconds = (tomorrow - now).total_seconds()
                
                await asyncio.sleep(sleep_seconds)
                
                # Reset daily usage
                await self.db_manager.reset_daily_usage()
                logger.info("Daily usage reset completed")
                
            except Exception as e:
                logger.error(f"Error in daily reset task: {e}")
                await asyncio.sleep(3600)  # Retry in 1 hour

# Additional utility classes and functions

class HealthChecker:
    """Health monitoring for the application"""
    
    def __init__(self, bot_instance):
        self.bot = bot_instance
    
    async def check_services(self) -> Dict[str, bool]:
        """Check health of all services"""
        health_status = {}
        
        # Check database connection
        try:
            result = self.bot.db_manager.supabase.table('users').select('count').execute()
            health_status['database'] = True
        except:
            health_status['database'] = False
        
        # Check Gemini API
        try:
            await self.bot.ai_processor._generate_with_gemini("Test", SummaryType.SHORT, "Test", "en")
            health_status['gemini_api'] = True
        except:
            health_status['gemini_api'] = False
        
        # Check Ollama (if configured)
        try:
            await self.bot.ai_processor._generate_with_ollama("Test", SummaryType.SHORT, "Test", "en")
            health_status['ollama'] = True
        except:
            health_status['ollama'] = False
        
        # Check Telegram API
        try:
            await self.bot.client.get_me()
            health_status['telegram'] = True
        except:
            health_status['telegram'] = False
        
        return health_status

class Analytics:
    """Analytics and reporting"""
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    async def get_usage_stats(self) -> Dict:
        """Get usage statistics"""
        try:
            # Total users
            users_result = self.db.supabase.table('users').select('count').execute()
            total_users = len(users_result.data) if users_result.data else 0
            
            # Total summaries
            summaries_result = self.db.supabase.table('video_summaries').select('count').execute()
            total_summaries = len(summaries_result.data) if summaries_result.data else 0
            
            # Active users (last 30 days)
            thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
            active_result = self.db.supabase.table('video_summaries').select('user_id').gte('created_at', thirty_days_ago).execute()
            active_users = len(set(item['user_id'] for item in active_result.data)) if active_result.data else 0
            
            return {
                'total_users': total_users,
                'total_summaries': total_summaries,
                'active_users_30d': active_users,
                'generated_at': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting usage stats: {e}")
            return {}

# Database schema creation (for initial setup)
async def create_database_tables():
    """Create necessary database tables"""
    
    sql_commands = [
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username VARCHAR(255),
            subscription_tier VARCHAR(50) DEFAULT 'free',
            subscription_expires TIMESTAMP WITH TIME ZONE,
            daily_usage INTEGER DEFAULT 0,
            total_summaries INTEGER DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            last_payment TIMESTAMP WITH TIME ZONE
        );
        """,
        
        """
        CREATE TABLE IF NOT EXISTS video_summaries (
            id VARCHAR(255) PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id),
            youtube_url TEXT,
            video_id VARCHAR(255),
            title TEXT,
            duration INTEGER,
            transcript TEXT,
            summary_short TEXT,
            summary_medium TEXT,
            summary_detailed TEXT,
            language VARCHAR(10),
            status VARCHAR(50),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            file_path TEXT
        );
        """,
        
        """
        CREATE TABLE IF NOT EXISTS payment_records (
            id VARCHAR(255) PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id),
            amount DECIMAL(10,2),
            currency VARCHAR(10),
            subscription_tier VARCHAR(50),
            stripe_session_id VARCHAR(255),
            status VARCHAR(50),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """,
        
        """
        CREATE INDEX IF NOT EXISTS idx_users_subscription_tier ON users(subscription_tier);
        CREATE INDEX IF NOT EXISTS idx_video_summaries_user_id ON video_summaries(user_id);
        CREATE INDEX IF NOT EXISTS idx_video_summaries_created_at ON video_summaries(created_at);
        CREATE INDEX IF NOT EXISTS idx_payment_records_user_id ON payment_records(user_id);
        """
    ]
    
    try:
        db = DatabaseManager()
        for command in sql_commands:
            db.supabase.rpc('execute_sql', {'sql': command}).execute()
        
        logger.info("Database tables created successfully")
        
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")

# Main execution
async def main():
    """Main entry point"""
    try:
        # Create database tables if needed
        await create_database_tables()
        
        # Initialize and start bot
        bot = YouTubeSummarizerBot()
        await bot.start()
        
    except Exception as e:
        logger.error(f"Failed to start application: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())