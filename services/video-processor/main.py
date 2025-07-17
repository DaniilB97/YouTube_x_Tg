# Этот файл создает сервис обработки YouTube видео - извлекает YouTubeProcessor и VideoFrameExtractor

# services/video-processor/main.py
import os
import asyncio
import logging
import tempfile
import shutil
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from urllib.parse import urlparse, parse_qs
import re

# Import shared components
import sys
sys.path.append('/app')
from shared.database import get_redis
from shared.models import TaskData, TaskType, TaskStatus
from shared.utils import extract_youtube_video_id, generate_task_id

# External libraries for video processing
import cv2
import numpy as np
from youtube_transcript_api import YouTubeTranscriptApi
from pytube import YouTube
import yt_dlp

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class YouTubeProcessor:
    """Handles YouTube video processing and transcript extraction"""
    
    def __init__(self):
        pass
    
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
            
            # Fallback - yt-dlp
            try:
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
                
                # Final fallback
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
        
        # FALLBACK: Signal that Whisper is needed (handled by AI service)
        logger.info(f"No transcript available via API for {video_id}, Whisper needed")
        return None, None

class VideoFrameExtractor:
    """Extract and analyze frames from YouTube videos"""
    
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp(prefix="video_frames_")
        self.extracted_frames = []
        
    def download_video_for_analysis(self, video_id: str) -> Optional[str]:
        """Download video in lower quality for frame extraction"""
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            
            # Download video in lower quality for faster processing
            ydl_opts = {
                'format': 'worst[height<=480]/worst',  # Lower quality
                'outtmpl': f'{self.temp_dir}/video_{video_id}.%(ext)s',
                'quiet': True,
                'no_warnings': True,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                },
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            # Find the downloaded file
            for file in os.listdir(self.temp_dir):
                if file.startswith(f'video_{video_id}'):
                    video_path = os.path.join(self.temp_dir, file)
                    logger.info(f"✅ Downloaded video for analysis: {video_path}")
                    return video_path
            
            return None
            
        except Exception as e:
            logger.error(f"Error downloading video for analysis: {e}")
            return None
    
    def extract_key_frames(self, video_path: str, max_frames: int = 15) -> List[Dict]:
        """Extract key frames from video using scene detection"""
        try:
            cap = cv2.VideoCapture(video_path)
            
            if not cap.isOpened():
                logger.error("Could not open video file")
                return []
            
            # Get video properties
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps if fps > 0 else 0
            
            logger.info(f"Video info: {total_frames} frames, {fps:.2f} fps, {duration:.2f}s")
            
            frames_data = []
            prev_frame = None
            frame_count = 0
            
            # Calculate interval to get evenly distributed frames
            interval = max(1, total_frames // max_frames)
            
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Process every nth frame
                if frame_count % interval == 0:
                    # Calculate timestamp
                    timestamp = frame_count / fps if fps > 0 else 0
                    
                    # Detect if this is a significant frame
                    is_key_frame = self.is_significant_frame(frame, prev_frame)
                    
                    if is_key_frame or len(frames_data) < 5:  # Always keep some frames
                        # Save frame
                        frame_filename = f"frame_{frame_count:06d}_{timestamp:.2f}s.jpg"
                        frame_path = os.path.join(self.temp_dir, frame_filename)
                        
                        cv2.imwrite(frame_path, frame)
                        
                        # Analyze frame content
                        frame_analysis = self.analyze_frame_content(frame, timestamp)
                        
                        frame_data = {
                            'frame_number': frame_count,
                            'timestamp': timestamp,
                            'path': frame_path,
                            'filename': frame_filename,
                            'is_key_frame': is_key_frame,
                            'analysis': frame_analysis
                        }
                        
                        frames_data.append(frame_data)
                        prev_frame = frame.copy()
                        
                        if len(frames_data) >= max_frames:
                            break
                
                frame_count += 1
            
            cap.release()
            self.extracted_frames = frames_data
            
            logger.info(f"✅ Extracted {len(frames_data)} key frames")
            return frames_data
            
        except Exception as e:
            logger.error(f"Error extracting frames: {e}")
            return []
    
    def is_significant_frame(self, current_frame, prev_frame) -> bool:
        """Detect if frame is significantly different from previous"""
        if prev_frame is None:
            return True
        
        try:
            # Convert to grayscale for comparison
            current_gray = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)
            prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
            
            # Calculate histogram difference
            hist_current = cv2.calcHist([current_gray], [0], None, [256], [0, 256])
            hist_prev = cv2.calcHist([prev_gray], [0], None, [256], [0, 256])
            
            # Compare histograms
            correlation = cv2.compareHist(hist_current, hist_prev, cv2.HISTCMP_CORREL)
            
            # If correlation is low, it's a significant change
            return correlation < 0.85
            
        except Exception as e:
            logger.warning(f"Error in frame comparison: {e}")
            return True
    
    def analyze_frame_content(self, frame, timestamp: float) -> Dict:
        """Analyze frame content for charts, text, etc."""
        try:
            analysis = {
                'timestamp': timestamp,
                'has_text': False,
                'has_charts': False,
                'brightness': 0,
                'edge_density': 0
            }
            
            # Convert to grayscale
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Calculate brightness
            analysis['brightness'] = np.mean(gray)
            
            # Simple edge detection for complexity
            edges = cv2.Canny(gray, 50, 150)
            analysis['edge_density'] = np.sum(edges > 0) / edges.size
            
            # Basic text detection (look for rectangular regions)
            contours, _ = cv2.findContours(gray, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            text_like_regions = 0
            
            for contour in contours:
                area = cv2.contourArea(contour)
                if 100 < area < 5000:  # Reasonable size for text
                    x, y, w, h = cv2.boundingRect(contour)
                    aspect_ratio = w / h if h > 0 else 0
                    if 0.2 < aspect_ratio < 8:  # Text-like aspect ratio
                        text_like_regions += 1
            
            analysis['has_text'] = text_like_regions > 5
            
            # Basic chart detection (look for straight lines)
            lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=50, minLineLength=100, maxLineGap=10)
            analysis['has_charts'] = lines is not None and len(lines) > 10
            
            return analysis
            
        except Exception as e:
            logger.warning(f"Error analyzing frame: {e}")
            return {
                'timestamp': timestamp,
                'has_text': False,
                'has_charts': False,
                'brightness': 0,
                'edge_density': 0
            }
    
    def cleanup(self):
        """Clean up temporary files"""
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            logger.info("✅ Cleaned up temporary files")
        except Exception as e:
            logger.warning(f"Error cleaning up: {e}")

class VideoProcessorService:
    """Main video processing service"""
    
    def __init__(self):
        self.redis = get_redis()
        self.youtube_processor = YouTubeProcessor()
        self.frame_extractor = VideoFrameExtractor()
        self.queue_name = 'video_processing_queue'
    
    async def start(self):
        """Start the video processing service"""
        await self.redis.connect()
        logger.info("✅ Video Processor Service started")
        
        # Start processing loop
        while True:
            try:
                await self.process_tasks()
            except Exception as e:
                logger.error(f"Error in processing loop: {e}")
                await asyncio.sleep(5)
    
    async def process_tasks(self):
        """Process video tasks from queue"""
        try:
            # Get task from queue
            task_data = await self.redis.dequeue_task(self.queue_name, timeout=30)
            
            if task_data:
                logger.info(f"Processing task {task_data.task_id}")
                await self.process_video_task(task_data)
            
        except Exception as e:
            logger.error(f"Error processing tasks: {e}")
    
    async def process_video_task(self, task_data: TaskData):
        """Process a single video task"""
        try:
            # Update status to processing
            await self.redis.set_task_status(task_data.task_id, TaskStatus.PROCESSING)
            
            # Extract data
            youtube_url = task_data.data.get('youtube_url')
            processing_type = task_data.data.get('processing_type', 'text_only')
            
            # Extract video ID
            video_id = extract_youtube_video_id(youtube_url)
            if not video_id:
                raise Exception("Invalid YouTube URL")
            
            # Get video info
            video_info = await self.youtube_processor.get_video_info(video_id)
            
            result = {
                'video_id': video_id,
                'video_info': video_info,
                'transcript': None,
                'language': None,
                'frames_data': None,
                'processing_type': processing_type
            }
            
            # Get transcript if needed
            if processing_type in ['text_only', 'full_analysis']:
                transcript, language = await self.youtube_processor.get_transcript(video_id)
                result['transcript'] = transcript
                result['language'] = language
            
            # Extract frames if needed
            if processing_type in ['frames_only', 'full_analysis']:
                video_path = self.frame_extractor.download_video_for_analysis(video_id)
                if video_path:
                    frames_data = self.frame_extractor.extract_key_frames(video_path)
                    result['frames_data'] = frames_data
                    # Cleanup video file
                    try:
                        os.remove(video_path)
                    except:
                        pass
            
            # Set completion status
            await self.redis.set_task_status(
                task_data.task_id, 
                TaskStatus.COMPLETED, 
                result=result
            )
            
            logger.info(f"✅ Completed task {task_data.task_id}")
            
        except Exception as e:
            logger.error(f"Error processing video task: {e}")
            await self.redis.set_task_status(
                task_data.task_id, 
                TaskStatus.FAILED, 
                error=str(e)
            )
        finally:
            # Cleanup
            self.frame_extractor.cleanup()

async def main():
    """Main entry point"""
    service = VideoProcessorService()
    await service.start()

if __name__ == "__main__":
    asyncio.run(main())