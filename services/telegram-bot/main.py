# Этот файл создает Telegram Bot Service - извлекает бота из монолита и подключает к API Gateway

# services/telegram-bot/main.py
import os
import asyncio
import logging
import tempfile
import shutil
from datetime import datetime
from typing import Optional, Dict, Any
import aiohttp
import re
import uuid 
import json
import yt_dlp

# Import shared components
import sys
sys.path.append('/app')
from shared.database import get_database, get_redis
from shared.models import User, SubscriptionTier
from shared.utils import extract_youtube_video_id, is_youtube_url, format_file_size

# Telegram libraries
from telethon import TelegramClient, events, Button
from telethon.tl.types import Message, MessageMediaDocument

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LanguageManager:
    """Manages multi-language support for the bot"""
    
    def __init__(self):
        self.languages = {
            'ru': {
                'start_welcome': """🎥 **YouTube Summarizer Bot - БЕТА ТЕСТ!**

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
/language - Изменить язык

Отправьте YouTube ссылку для начала! 🎯""",

                'processing_video': '⏳ **Обрабатываю видео...**\n\n**Название:** {title}\n**Длительность:** {duration}\n\nЭто может занять несколько минут...',
                'processing_audio': '🎵 **Обрабатываю аудио...**\n\nИзвлекаю текст из аудио...',
                'processing_completed': '✅ **Обработка завершена!**',
                'processing_failed': '❌ **Обработка не удалась**',
                'error_occurred': 'Произошла ошибка: {error}',
                'invalid_url': '❌ Неверная YouTube ссылка. Проверьте URL.',
                'user_not_found': '❌ Пользователь не найден. Используйте /start',
                'help_message': """📖 **Справка по YouTube Summarizer Bot**

**Команды:**
/start - Приветствие и настройка
/help - Эта справка
/status - Статус аккаунта
/language - Изменить язык

**Поддерживаемые форматы:**
• YouTube URLs (любые ссылки)
• Голосовые сообщения Telegram
• Аудио файлы (MP3, WAV, M4A, OGG)

Бот находится в режиме бета-тестирования! 🚀""",

                'status_message': """📊 **Ваш статус**

**Режим:** БЕТА-ТЕСТ (все бесплатно!)
**Пользователь:** {username}
**Язык:** {language}

**Доступные функции:**
✅ YouTube видео (без ограничений)
✅ Голосовые сообщения
✅ Аудио файлы

Наслаждайтесь бесплатным использованием! 🎉""",

                'choose_language': 'Выберите язык:',
                'language_changed': 'Язык изменен на русский 🇷🇺',
                'default_response': """Отправьте:
- 📹 YouTube ссылку
- 🎵 Голосовое сообщение  
- 🎧 Аудио файл (MP3, WAV, M4A)

Команды: /help /status /language""",
            },
            
            'en': {
                'start_welcome': """🎥 **YouTube Summarizer Bot - BETA TEST!**

Hello {username}! All features are temporarily free! 🚀

**What I can do:**
• 📹 YouTube videos → summary
• 🎵 Voice messages → text  
• 🎧 Audio files → summary

**Just send:**
- YouTube link
- Voice message
- Audio file

**Commands:**
/help - Help
/status - Status
/history - History
/language - Change language

Send a YouTube link to get started! 🎯""",

                'processing_video': '⏳ **Processing video...**\n\n**Title:** {title}\n**Duration:** {duration}\n\nThis may take several minutes...',
                'processing_audio': '🎵 **Processing audio...**\n\nExtracting text from audio...',
                'processing_completed': '✅ **Processing completed!**',
                'processing_failed': '❌ **Processing failed**',
                'error_occurred': 'An error occurred: {error}',
                'invalid_url': '❌ Invalid YouTube link. Please check the URL.',
                'user_not_found': '❌ User not found. Use /start',
                'help_message': """📖 **YouTube Summarizer Bot Help**

**Commands:**
/start - Welcome and setup
/help - This help
/status - Account status
/language - Change language

**Supported formats:**
• YouTube URLs (any links)
• Telegram voice messages
• Audio files (MP3, WAV, M4A, OGG)

Bot is in beta testing mode! 🚀""",

                'status_message': """📊 **Your Status**

**Mode:** BETA-TEST (everything free!)
**User:** {username}
**Language:** {language}

**Available features:**
✅ YouTube videos (unlimited)
✅ Voice messages
✅ Audio files

Enjoy free usage! 🎉""",

                'choose_language': 'Choose language:',
                'language_changed': 'Language changed to English 🇺🇸',
                'default_response': """Send:
- 📹 YouTube link
- 🎵 Voice message  
- 🎧 Audio file (MP3, WAV, M4A)

Commands: /help /status /language""",
            }
        }
        
        self.available_languages = {
            'ru': '🇷🇺 Русский',
            'en': '🇺🇸 English'
        }
        
        self.default_language = 'ru'
    
    def get_text(self, user_language: str, key: str, **kwargs) -> str:
        """Get localized text for a user"""
        lang = user_language if user_language in self.languages else self.default_language
        text = self.languages[lang].get(key, self.languages[self.default_language].get(key, f"Missing translation: {key}"))
        
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text

class KeyboardManager:
    """Manages all keyboard layouts and buttons for the bot"""
    
    def __init__(self, language_manager):
        self.lang = language_manager
    
    def get_language_selection_keyboard(self):
        """Get inline keyboard for language selection"""
        buttons = []
        for code, name in self.lang.available_languages.items():
            buttons.append([Button.inline(name, f"lang_{code}")])
        return buttons

class TelegramBotService:
    """Main Telegram Bot Service - communicates with API Gateway"""
    
    def __init__(self):
        # Initialize Telegram client
        self.client = TelegramClient(
            'youtube_summarizer',
            int(os.getenv('TELEGRAM_API_ID')),
            os.getenv('TELEGRAM_API_HASH')
        )
        
        # Initialize managers
        self.db = get_database()
        self.redis = get_redis()
        self.language_manager = LanguageManager()
        self.keyboard_manager = KeyboardManager(self.language_manager)
        
        # API Gateway URL
        self.api_gateway_url = os.getenv('API_GATEWAY_URL', 'http://api-gateway:8000')
        
        # Processing tasks tracking
        self.processing_tasks = {}
        
        # URL validation pattern
        self.youtube_url_pattern = re.compile(
            r'(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)[A-Za-z0-9_-]{11}'
        )
    
    def telegram_id_to_uuid(self, telegram_user_id: str) -> str:
        """Convert Telegram user ID to deterministic UUID"""
        # Создаем детерминированный UUID на основе Telegram ID
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"telegram:{telegram_user_id}"))

    async def start(self):
        """Start the Telegram bot service"""
        logger.info("Starting Telegram Bot Service...")
        
        # Start the client
        await self.client.start(bot_token=os.getenv('TELEGRAM_BOT_TOKEN'))
        
        # Connect to Redis for status updates
        await self.redis.connect()
        
        # Subscribe to task status updates
        await self.redis.subscribe_to_channel("task_status:*", self.handle_task_status_update)
        
        # Register event handlers
        self.register_handlers()
        
        logger.info("✅ Telegram Bot Service started successfully!")
        await self.client.run_until_disconnected()
    
    def register_handlers(self):
        """Register all Telegram event handlers"""
        
        @self.client.on(events.NewMessage(pattern='/start'))
        async def handle_start(event):
            await self.handle_start_command(event)

        @self.client.on(events.NewMessage(pattern='/help'))
        async def handle_help(event):
            await self.handle_help_command(event)
            
        @self.client.on(events.NewMessage(pattern='/status'))
        async def handle_status(event):
            await self.handle_status_command(event)
            
        @self.client.on(events.NewMessage(pattern='/language'))
        async def handle_language(event):
            await self.handle_language_command(event)

        @self.client.on(events.NewMessage())
        async def handle_message(event):
            await self.handle_any_message(event)
            
        @self.client.on(events.CallbackQuery())
        async def handle_callback(event):
            await self.handle_callback_query(event)
    
    async def handle_start_command(self, event):
        """Handle /start command with main menu"""
        try:
            telegram_user_id = str(event.sender_id)
            user_id = self.telegram_id_to_uuid(telegram_user_id)
            username = event.sender.username or f"user_{telegram_user_id}"
            
            # Get or create user
            user = await self.get_or_create_user(user_id, username)
            
            welcome_msg = self.language_manager.get_text(
                user.language, 
                'start_welcome',
                username=username
            )
            
            # 🔥 ПОСТОЯННЫЕ КНОПКИ ВНИЗУ ЭКРАНА:
            from telethon.tl.types import KeyboardButtonRow, KeyboardButton, ReplyKeyboardMarkup
            
            permanent_keyboard = ReplyKeyboardMarkup(
                rows=[
                    KeyboardButtonRow([
                        KeyboardButton("📹 Обработать видео"),
                        KeyboardButton("💬 Мои видео")
                    ]),
                    KeyboardButtonRow([
                        KeyboardButton("🌐 Язык"),
                        KeyboardButton("📊 История"),
                        KeyboardButton("⭐ Отзыв")
                    ])
                ],
                resize=True,
                persistent=True
            )
            
            await event.reply(welcome_msg, buttons=permanent_keyboard)
            
        except Exception as e:
            logger.error(f"Error in start command: {e}")
            await event.reply("❌ Произошла ошибка. Попробуйте снова.")
    
    async def handle_help_command(self, event):
        """Handle /help command"""
        try:
            telegram_user_id = str(event.sender_id)
            user_id = self.telegram_id_to_uuid(telegram_user_id) # convert to UUID
            user = await self.db.get_user(user_id)
            
            if not user:
                await event.reply(self.language_manager.get_text('ru', 'user_not_found'))
                return
            
            help_msg = self.language_manager.get_text(user.language, 'help_message')
            await event.reply(help_msg)
            
        except Exception as e:
            logger.error(f"Error in help command: {e}")
    
    async def handle_status_command(self, event):
        """Handle /status command"""
        try:
            telegram_user_id = str(event.sender_id)
            user_id = self.telegram_id_to_uuid(telegram_user_id) # converting to UUID
            user = await self.db.get_user(user_id)
            
            if not user:
                await event.reply(self.language_manager.get_text('ru', 'user_not_found'))
                return

            status_msg = self.language_manager.get_text(
                user.language,
                'status_message',
                username=user.username,
                language=self.language_manager.available_languages.get(user.language)
            )
            
            await event.reply(status_msg)
            
        except Exception as e:
            logger.error(f"Error in status command: {e}")
    
    async def handle_language_command(self, event):
        """Handle /language command"""
        try:
            telegram_user_id = str(event.sender_id)
            user_id = self.telegram_id_to_uuid(telegram_user_id)
            user = await self.db.get_user(user_id)
            
            if not user:
                await event.reply(self.language_manager.get_text('ru', 'user_not_found'))
                return

            choose_text = self.language_manager.get_text(user.language, 'choose_language')
            keyboard = self.keyboard_manager.get_language_selection_keyboard()
            
            await event.reply(choose_text, buttons=keyboard)
            
        except Exception as e:
            logger.error(f"Error in language command: {e}")
    
    async def handle_any_message(self, event):
        """Handle all other messages"""
        try:
            # Skip commands
            if event.message.text and event.message.text.startswith('/'):
                return
            
            telegram_user_id = str(event.sender_id)
            user_id = self.telegram_id_to_uuid(telegram_user_id)
            username = event.sender.username or f"user_{telegram_user_id}"
            
            # 🔥 ДОБАВИТЬ ЭТУ СТРОКУ СЮДА:
            message_text = event.message.text

            
            
            # Проверка отзывов
            if hasattr(self, 'waiting_for_feedback') and event.sender_id in self.waiting_for_feedback:
                feedback_state = self.waiting_for_feedback[event.sender_id]
                if feedback_state.get('step') == 'waiting_comment':
                    comment = message_text
                    rating = feedback_state['rating']
                    await self.finish_feedback(event, rating, comment)
                    return

            user = await self.get_or_create_user(user_id, username)
            
            if message_text:
                if message_text == "📹 Обработать видео":
                    await self.show_video_input_prompt(event)
                    return
                elif message_text == "💬 Мои видео":
                    await self.show_my_videos(event)
                    return
                elif message_text == "🌐 Язык":
                    await self.show_language_selection(event)
                    return
                elif message_text == "📊 История":
                    await self.show_history(event)
                    return
                elif message_text == "⭐ Отзыв":
                    await self.show_feedback_rating(event)
                    return
            
            # YouTube URLs
            if message_text and self.youtube_url_pattern.search(message_text):
                await self.handle_youtube_url(event, user)
                return
            
            # Voice messages
            if event.message.voice:
                await self.handle_voice_message(event, user)
                return
            
            # Documents (audio files)
            if event.message.document:
                doc = event.message.document
                if doc.mime_type and doc.mime_type.startswith('audio/'):
                    await self.handle_audio_file(event, user)
                    return
            
            # Default response
            default_msg = self.language_manager.get_text(user.language, 'send_youtube_url')
            await event.reply(default_msg)
            
        except Exception as e:
            logger.error(f"Error handling message: {e}")
        
    async def handle_callback_query(self, event):
        """Handle inline button clicks"""
        try:
            data = event.data.decode('utf-8')
            user_id = str(event.sender_id)
            
            # Language selection
            if data.startswith('lang_'):
                await self.handle_language_selection(event, data, user_id)
            
            # 🔥 НОВОЕ: Обработка кнопок типа процессинга
            elif data == "menu_process_video":
                await self.show_video_input_prompt(event)
            elif data == "menu_my_videos":
                await self.show_my_videos(event)
            elif data == "menu_language":
                await self.show_language_selection(event)
            elif data == "menu_history":
                await self.show_history(event)
            elif data == "menu_feedback":
                await self.show_feedback_rating(event)
            elif data == "process_text_only":
                await self.handle_process_selection(event, "text_only", "txt")
            elif data == "process_files":
                await self.show_file_format_selection(event)
            elif data == "process_full":
                await self.show_full_analysis_selection(event)
            elif data == "back_to_menu":
                await self.show_main_menu(event)
            elif data.startswith("rate_"):
                rating = int(data.replace("rate_", ""))
                await self.handle_rating_selection(event, rating)
            elif data.startswith("comment_"):
                rating = int(data.replace("comment_", ""))
                await self.show_comment_input(event, rating)
            elif data.startswith("finish_feedback_"):
                rating = int(data.replace("finish_feedback_", ""))
                await self.finish_feedback(event, rating, None)
            
                
            # 🔥 НОВОЕ: Обработка кнопок формата файлов
            elif data.startswith("format_"):
                format_type = data.replace("format_", "")
                await self.handle_process_selection(event, "files", format_type)
                
            # 🔥 НОВОЕ: Обработка кнопок полного анализа
            elif data.startswith("full_"):
                format_type = data.replace("full_", "")
                await self.handle_process_selection(event, "full_analysis", format_type)
            
            await event.answer()
            
        except Exception as e:
            logger.error(f"Error handling callback: {e}")
            await event.answer("Error occurred")
    
    async def handle_language_selection(self, event, data: str, telegram_user_id: str):
        """Handle language selection from inline keyboard"""
        try:
            user_id = self.telegram_id_to_uuid(telegram_user_id)  # Convert to UUID
            language_code = data.replace('lang_', '')
            
            if language_code in self.language_manager.languages:
                # Update user language in database
                success = await self.db.update_user_language(user_id, language_code)
                
                if success:
                    confirmation_msg = self.language_manager.get_text(language_code, 'language_changed')
                    await event.edit(confirmation_msg)
                else:
                    await event.answer("Failed to update language")
            else:
                await event.answer("Language not supported")
                
        except Exception as e:
            logger.error(f"Error in language selection: {e}")
            await event.answer("Error occurred")
    
    async def show_main_menu(self, event):
        """Show main menu"""
        main_menu = [
            [Button.inline("📹 Обработать видео", data="menu_process_video")],
            [Button.inline("💬 Мои видео", data="menu_my_videos"),
            Button.inline("🌐 Язык", data="menu_language")],
            [Button.inline("📊 История", data="menu_history"),
            Button.inline("⭐ Отзыв", data="menu_feedback")]
        ]
        
        await event.edit("🤖 **YouTube Summarizer Bot**\n\nВыберите действие:", buttons=main_menu)

    async def show_video_input_prompt(self, event):
        """Show video input prompt"""
        msg = "📹 **Отправьте YouTube ссылку**\n\nПришлите ссылку на видео которое хотите обработать:"
        buttons = [[Button.inline("🔙 Назад в меню", data="back_to_menu")]]
        
        try:
            if hasattr(event, 'message') and event.message:
                await event.reply(msg, buttons=buttons)
            else:
                await event.edit(msg, buttons=buttons)
        except Exception as e:
            logger.error(f"Error showing video input prompt: {e}")
            await event.reply(msg, buttons=buttons)

    async def show_my_videos(self, event):
        """Show user's processed videos"""
        msg = "💬 **Ваши видео**\n\n🚧 Функция в разработке...\n\nСкоро здесь будет список ваших обработанных видео с возможностью обсуждения!"
        buttons = [[Button.inline("🔙 Назад в меню", data="back_to_menu")]]
        
        try:
            if hasattr(event, 'message') and event.message:
                await event.reply(msg, buttons=buttons)
            else:
                await event.edit(msg, buttons=buttons)
        except Exception as e:
            logger.error(f"Error showing my videos: {e}")
            await event.reply(msg, buttons=buttons)

    async def show_language_selection(self, event):
        """Show language selection menu"""
        buttons = [
            [Button.inline("🇷🇺 Русский", data="lang_ru"),
            Button.inline("🇺🇸 English", data="lang_en")],
            [Button.inline("🔙 Назад в меню", data="back_to_menu")]
        ]
        
        msg = "🌐 **Выберите язык:**\n\nSelect your language:"
        
        try:
            if hasattr(event, 'message') and event.message:
                await event.reply(msg, buttons=buttons)
            else:
                await event.edit(msg, buttons=buttons)
        except Exception as e:
            logger.error(f"Error showing language selection: {e}")
            await event.reply(msg, buttons=buttons)

    async def show_history(self, event):
        """Show processing history"""
        try:
            # Если это постоянная кнопка - отправляем новое сообщение
            if hasattr(event, 'message') and event.message:
                await event.reply(
                    "📊 **История обработки**\n\n🚧 Функция в разработке...\n\nЗдесь будет статистика ваших обработанных видео!",
                    buttons=[[Button.inline("🔙 Назад в меню", data="back_to_menu")]]
                )
            # Если это inline кнопка - редактируем сообщение
            else:
                await event.edit(
                    "📊 **История обработки**\n\n🚧 Функция в разработке...\n\nЗдесь будет статистика ваших обработанных видео!",
                    buttons=[[Button.inline("🔙 Назад в меню", data="back_to_menu")]]
                )
        except Exception as e:
            logger.error(f"Error showing history: {e}")
            await event.reply("❌ Ошибка при показе истории")

    async def show_feedback_rating(self, event):
        """Show feedback rating stars"""
        rating_buttons = [
            [Button.inline("⭐", data="rate_1"),
            Button.inline("⭐⭐", data="rate_2"),
            Button.inline("⭐⭐⭐", data="rate_3")],
            [Button.inline("⭐⭐⭐⭐", data="rate_4"),
            Button.inline("⭐⭐⭐⭐⭐", data="rate_5")],
            [Button.inline("🔙 Назад в меню", data="back_to_menu")]
        ]
        
        msg = "⭐ **Оцените наш сервис:**\n\nВыберите количество звезд от 1 до 5:"
        
        try:
            if hasattr(event, 'message') and event.message:
                await event.reply(msg, buttons=rating_buttons)
            else:
                await event.edit(msg, buttons=rating_buttons)
        except Exception as e:
            logger.error(f"Error showing feedback rating: {e}")
            await event.reply(msg, buttons=rating_buttons)

    async def handle_rating_selection(self, event, rating: int):
        """Handle rating selection"""
        # Сохраняем рейтинг пользователя
        user_id = str(event.sender_id)
        
        # Показываем форму для комментария
        comment_buttons = [
            [Button.inline("✍️ Оставить комментарий", data=f"comment_{rating}")],
            [Button.inline("➡️ Пропустить", data=f"finish_feedback_{rating}")],
            [Button.inline("🔙 Назад в меню", data="back_to_menu")]
        ]
        
        await event.edit(
            f"⭐ **Спасибо за оценку {rating}/5!**\n\nХотите добавить комментарий?",
            buttons=comment_buttons
        )

    async def show_comment_input(self, event, rating: int):
        """Show comment input prompt"""
        await event.edit(
            f"✍️ **Оставьте комментарий (оценка: {rating}/5)**\n\nНапишите ваш отзыв одним сообщением:",
            buttons=[[Button.inline("🔙 Назад к оценкам", data="menu_feedback")]]
        )
        
        # Сохраняем состояние ожидания комментария
        if not hasattr(self, 'waiting_for_feedback'):
            self.waiting_for_feedback = {}
        
        self.waiting_for_feedback[event.sender_id] = {
            'rating': rating,
            'step': 'waiting_comment'
        }

    async def finish_feedback(self, event, rating: int, comment: str = None):
        """Finish feedback process and save to database"""
        try:
            user_id = str(event.sender_id)
            
            # Здесь можно сохранить отзыв в базу данных
            # await self.save_feedback(user_id, rating, comment)
            
            # Показываем благодарность
            thanks_msg = f"🙏 **Спасибо за отзыв!**\n\n⭐ Оценка: {rating}/5"
            if comment:
                thanks_msg += f"\n💬 Комментарий: {comment[:100]}{'...' if len(comment) > 100 else ''}"
            
            await event.edit(
                thanks_msg + "\n\nВаш отзыв поможет нам стать лучше!",
                buttons=[[Button.inline("🔙 Главное меню", data="back_to_menu")]]
            )
            
            # Очищаем состояние
            if hasattr(self, 'waiting_for_feedback') and event.sender_id in self.waiting_for_feedback:
                del self.waiting_for_feedback[event.sender_id]
                
            logger.info(f"Feedback received: user={user_id}, rating={rating}, comment_length={len(comment) if comment else 0}")
            
        except Exception as e:
            logger.error(f"Error finishing feedback: {e}")
            await event.edit("❌ Ошибка при сохранении отзыва")

    async def handle_youtube_url(self, event, user: User):
        """Handle YouTube URL processing with format selection"""
        try:
            youtube_url = event.message.text
            video_id = extract_youtube_video_id(youtube_url)
            
            if not video_id:
                await event.reply(self.language_manager.get_text(user.language, 'invalid_url'))
                return
            
            # Получаем информацию о видео
            try:
                
                # Получаем метаданные через yt-dlp
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'extract_flat': False,
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(youtube_url, download=False)
                    title = info.get('title', f"YouTube Video {video_id}")
                    author = info.get('uploader', 'Unknown')
                    duration_seconds = info.get('duration', 0)
                    
                    # Форматируем длительность
                    if duration_seconds:
                        minutes = duration_seconds // 60
                        seconds = duration_seconds % 60
                        duration_text = f"{minutes}:{seconds:02d}"
                    else:
                        duration_text = "Неизвестно"
                        
            except Exception as e:
                logger.warning(f"Could not get video metadata with yt-dlp: {e}")
                # Fallback к старому способу
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(f"https://www.youtube.com/oembed?url={youtube_url}&format=json") as resp:
                            if resp.status == 200:
                                video_info = await resp.json()
                                title = video_info.get('title', f"YouTube Video {video_id}")
                                author = video_info.get('author_name', 'Unknown')
                            else:
                                title = f"YouTube Video {video_id}"
                                author = 'Unknown'
                except:
                    title = f"YouTube Video {video_id}"
                    author = 'Unknown'
                
                duration_text = "Неизвестно"
            
            # 🔥 НОВОЕ: Отправляем кнопки выбора типа обработки
            buttons = [
                [Button.inline("📝 Только текст", data="process_text_only")],
                [Button.inline("📄 Файлы", data="process_files"), 
                    Button.inline("🎬 Полный анализ", data="process_full")],
            ]
            
            processing_msg = await event.reply(
                f"📹 **{title}**\n👤 *{author}*\n⏱️ *{duration_text}*\n\n🎬 Что сделать с видео?\n\nВыберите тип обработки:",
                buttons=buttons
            )
            
            # 🔥 НОВОЕ: Сохраняем состояние пользователя вместо сразу отправки запроса
            if not hasattr(self, 'user_states'):
                self.user_states = {}
                
            self.user_states[event.sender_id] = {
                'url': youtube_url,
                'video_id': video_id,
                'title': title,
                'author': author,
                'duration': duration_text,
                'chat_id': event.chat_id,
                'message_id': processing_msg.id,
                'user': user,
                'step': 'awaiting_process_type'
            }
            
            logger.info(f"Video selection UI shown for: {title}")
            
        except Exception as e:
            logger.error(f"Error handling YouTube URL: {e}")
            await event.reply(self.language_manager.get_text(user.language, 'error_occurred', error=str(e)))
    
    async def handle_voice_message(self, event, user: User):
        """Handle voice message processing"""
        try:
            # Send processing message
            processing_msg = await event.reply(
                self.language_manager.get_text(user.language, 'processing_audio')
            )
            
            # Download voice message
            voice_file = await self.download_voice_message(event.message)
            if not voice_file:
                await processing_msg.edit(self.language_manager.get_text(user.language, 'processing_failed'))
                return
            
            # Send request to API Gateway
            task_id = await self.send_audio_processing_request(user, voice_file, "Voice Message", event.chat_id)
            
            if task_id:
                self.processing_tasks[task_id] = {
                    'user_id': user.user_id,
                    'chat_id': event.chat_id,
                    'message_id': processing_msg.id,
                    'type': 'audio'
                }
                logger.info(f"Audio processing task created: {task_id}")
            else:
                await processing_msg.edit(self.language_manager.get_text(user.language, 'processing_failed'))
            
        except Exception as e:
            logger.error(f"Error handling voice message: {e}")
    
    async def handle_audio_file(self, event, user: User):
        """Handle audio file processing"""
        try:
            doc = event.message.document
            file_name = doc.attributes[0].file_name if doc.attributes else "audio_file"
            file_size_mb = doc.size / (1024 * 1024)
            
            if file_size_mb > 50:
                await event.reply(f"❌ Файл слишком большой ({file_size_mb:.1f} MB). Максимум 50 MB.")
                return
            
            processing_msg = await event.reply(
                self.language_manager.get_text(user.language, 'processing_audio')
            )
            
            # Download audio file
            audio_file = await self.download_audio_file(event.message, file_name)
            if not audio_file:
                await processing_msg.edit(self.language_manager.get_text(user.language, 'processing_failed'))
                return
            
            # Send request to API Gateway
            task_id = await self.send_audio_processing_request(user, audio_file, file_name, event.chat_id)
            
            if task_id:
                self.processing_tasks[task_id] = {
                    'user_id': user.user_id,
                    'chat_id': event.chat_id,
                    'message_id': processing_msg.id,
                    'type': 'audio'
                }
                logger.info(f"Audio processing task created: {task_id}")
            else:
                await processing_msg.edit(self.language_manager.get_text(user.language, 'processing_failed'))
            
        except Exception as e:
            logger.error(f"Error handling audio file: {e}")
    
    async def send_video_processing_request(self, user: User, youtube_url: str, chat_id: int, processing_type: str = "text_only", file_format: str = "txt") -> Optional[str]:
        """Send video processing request to API Gateway"""
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "user_id": user.user_id,
                    "chat_id": chat_id,
                    "youtube_url": youtube_url,
                    "processing_type": processing_type,
                    "file_format": file_format
                }
                
                async with session.post(
                    f"{self.api_gateway_url}/api/v1/video/process",
                    json=payload
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('task_id')
                    else:
                        logger.error(f"API Gateway error: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error sending video processing request: {e}")
            return None
    
    async def send_audio_processing_request(self, user: User, file_path: str, title: str, chat_id: int) -> Optional[str]:
        """Send audio processing request to API Gateway"""
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "user_id": user.user_id,
                    "chat_id": chat_id,
                    "audio_type": "voice_message",
                    "file_path": file_path,
                    "title": title
                }
                
                async with session.post(
                    f"{self.api_gateway_url}/api/v1/audio/process",
                    json=payload
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('task_id')
                    else:
                        logger.error(f"API Gateway error: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error sending audio processing request: {e}")
            return None
    
    async def handle_task_status_update(self, channel: str, data: Dict):
        """Handle task status updates from Redis"""
        try:
            logger.info(f"🔔 RECEIVED status update from channel: {channel}")
            logger.info(f"🔔 Status data: {data}")
            
            # 🔥 ИСПРАВЛЕНИЕ: Декодируем bytes в string
            if isinstance(channel, bytes):
                channel = channel.decode('utf-8')
            
            # Extract task_id from channel name
            task_id = channel.split(':')[-1]
            logger.info(f"🔔 Extracted task_id: {task_id}")
            
            if task_id in self.processing_tasks:
                task_info = self.processing_tasks[task_id]
                status = data.get('status')
                
                if status == 'processing':
                    await self.update_progress_message(task_id, task_info, data)
                elif status == 'completed':
                    await self.handle_task_completion(task_id, task_info, data)
                elif status == 'failed':
                    await self.handle_task_failure(task_id, task_info, data)
                    
        except Exception as e:
            logger.error(f"❌ Error handling task status update: {e}")
    
    async def handle_task_completion(self, task_id: str, task_info: Dict, data: Dict):
        """Handle completed task"""
        try:
            user = await self.db.get_user(task_info['user_id'])
            if not user:
                return
            
            completion_msg = f"""✅ **Обработка завершена!**

    🎬 **{task_info.get('title', 'YouTube Video')}**
    👤 *{task_info.get('author', 'Unknown')}*

    📊 **Прогресс:**
    {self.get_progress_bar(100)} 100% - Готово!

    ⏱️ Обработано за {self.get_processing_time(task_id)}"""
            
            # Edit the processing message
            await self.client.edit_message(
                task_info['chat_id'],
                task_info['message_id'],
                completion_msg
            )
            
            # Send result
            result = data.get('result', {})
            if isinstance(result, str):
                result = json.loads(result)  # Parse JSON string
                
            if task_info['type'] == 'video':
                summary = result.get('summary_short', 'Summary not available')
                await self.client.send_message(task_info['chat_id'], f"📝 **Summary:**\n{summary}")
                
                # 🔥 ДОБАВИТЬ ОТПРАВКУ ФАЙЛА:
                # 🔥 ПРАВИЛЬНАЯ ОТПРАВКА ФАЙЛА ОТ FILE MANAGER:
                files = result.get('files', [])
                if files and len(files) > 0:
                    for file_info in files:
                        file_path = file_info.get('path')
                        filename = file_info.get('filename', 'summary_file')
                        
                        if file_path and file_path.endswith(('.md', '.txt', '.pdf')):
                            logger.info(f"📤 Attempting to send file: {file_path}")
                            try:
                                await self.client.send_file(
                                    task_info['chat_id'], 
                                    file_path,
                                    caption=f"📄 {filename}"
                                )
                                logger.info(f"✅ File sent successfully: {filename}")
                            except Exception as e:
                                logger.error(f"❌ Error sending file {file_path}: {e}")
                        else:
                            logger.warning(f"⚠️ Skipping invalid file: {file_path}")
                else:
                    logger.warning(f"❌ No files found in result. Available keys: {list(result.keys())}")
                    # Отправляем хотя бы текстовый результат
                    full_summary = result.get('summaries', {})
                    if full_summary:
                        summary_text = full_summary.get('medium', full_summary.get('short', 'No summary available'))
                        await self.client.send_message(task_info['chat_id'], f"📄 **Полный текст:**\n\n{summary_text}")
            
            # Cleanup
            del self.processing_tasks[task_id]
            
        except Exception as e:
            logger.error(f"Error handling task completion: {e}")
    # отработать эту заглушку 
    def get_processing_time(self, task_id: str) -> str:
        """Calculate processing time (placeholder)"""
        # Пока заглушка, потом можно добавить реальный подсчет
        return "1 мин 23 сек"

    async def handle_task_failure(self, task_id: str, task_info: Dict, data: Dict):
        """Handle failed task"""
        try:
            user = await self.db.get_user(task_info['user_id'])
            if not user:
                return
            
            error_msg = self.language_manager.get_text(
                user.language, 
                'processing_failed'
            )
            
            await self.client.edit_message(
                task_info['chat_id'],
                task_info['message_id'],
                error_msg
            )
            
            # Cleanup
            del self.processing_tasks[task_id]
            
        except Exception as e:
            logger.error(f"Error handling task failure: {e}")

    def get_progress_bar(self, percent: int) -> str:
        """Generate beautiful star progress bar"""
        filled = int(percent / 10)
        return '⭐' * filled + '⚫' * (10 - filled)

    def get_processing_stage(self, data: Dict, result: Dict) -> Dict:
        """Determine processing stage based on data"""
        # Анализируем откуда пришло обновление
        if 'transcript' in result:
            # Audio Processor завершил
            return {
                'bar': self.get_progress_bar(60),
                'percent': 60,
                'message': 'Генерирую саммари с ИИ...',
                'time_estimate': 'Осталось ~30-60 секунд'
            }
        elif 'summaries' in result:
            # AI Processor завершил
            return {
                'bar': self.get_progress_bar(90),
                'percent': 90,
                'message': 'Создаю файлы...',
                'time_estimate': 'Осталось ~10 секунд'
            }
        else:
            # Начальная стадия
            return {
                'bar': self.get_progress_bar(30),
                'percent': 30,
                'message': 'Загружаю и обрабатываю аудио...',
                'time_estimate': 'Осталось ~1-2 минуты'
            }

    async def update_progress_message(self, task_id: str, task_info: Dict, data: Dict):
        """Update progress message with current status"""
        try:
            result = data.get('result', {})
            if isinstance(result, str):
                result = json.loads(result)
            
            # Определяем этап обработки по источнику
            stage_info = self.get_processing_stage(data, result)
            
            progress_msg = f"""⏳ **Обрабатываю видео...**

    🎬 **{task_info.get('title', 'YouTube Video')}**
    👤 *{task_info.get('author', 'Unknown')}*

    🔧 Режим: {task_info.get('processing_type', 'files')}

    📊 **Прогресс:**
    {stage_info['bar']} {stage_info['percent']}% - {stage_info['message']}

    ⏱️ {stage_info['time_estimate']}"""

            await self.client.edit_message(
                task_info['chat_id'],
                task_info['message_id'],
                progress_msg
            )
            
        except Exception as e:
            logger.error(f"Error updating progress: {e}")

    async def handle_process_selection(self, event, processing_type: str, file_format: str):
        """Handle processing type selection and start processing"""
        try:
            user_state = self.user_states.get(event.sender_id)
            if not user_state:
                await event.edit("❌ Сессия истекла. Отправьте ссылку заново.")
                return
            
            # Формируем сообщение о начале обработки
            format_display = {
                'txt': 'TXT',
                'md': 'Markdown', 
                'pdf': 'PDF',
                'all': 'все форматы'
            }.get(file_format, file_format.upper())

            # Маппинг для File Manager (отдельно!)
            format_mapping = {
                'txt': 'txt',    # txt
                'md': 'markdown',     # Markdown → Markdown файл  
                'pdf': 'pdf',         # PDF → PDF файл
                'all': 'both'         # Все → PDF + Markdown
            }

            mapped_format = format_mapping.get(file_format, 'markdown')
            
            process_text = {
                'text_only': '📝 Только текст',
                'files': f'📄 Файлы ({format_display})',        # ← format_display
                'full_analysis': f'🎬 Полный анализ ({format_display})'  # ← format_display
            }.get(processing_type, processing_type)
            
            # Обновляем сообщение
            # 🔥 НОВОЕ:
            progress_msg = f"""⏳ **Обрабатываю видео...**

            🎬 **{user_state['title']}**
            👤 *{user_state['author']}*

            🔧 Режим: {process_text}

            📊 **Прогресс:**
            {self.get_progress_bar(0)} 0% - Подготовка...

            ⏱️ Оценочное время: 1-2 минуты"""

            await event.edit(progress_msg)
            
            # Отправляем запрос в API Gateway
            task_id = await self.send_video_processing_request(
                user=user_state['user'],
                youtube_url=user_state['url'],
                chat_id=user_state['chat_id'],
                processing_type=processing_type,
                file_format=mapped_format
            )
            
            if task_id:
                # Сохраняем информацию о задаче для отслеживания статуса
                self.processing_tasks[task_id] = {
                    'user_id': user_state['user'].user_id,
                    'chat_id': user_state['chat_id'],
                    'message_id': user_state['message_id'],
                    'type': 'video',
                    'processing_type': processing_type,
                    'file_format': mapped_format
                }
                
                # Убираем состояние пользователя
                del self.user_states[event.sender_id]
                
                logger.info(f"Video processing task created: {task_id} ({processing_type}, {file_format})")
            else:
                await event.edit("❌ **Ошибка обработки**\n\nНе удалось отправить запрос. Попробуйте позже.")
                
        except Exception as e:
            logger.error(f"Error in handle_process_selection: {e}")
            await event.edit("❌ **Произошла ошибка**\n\nПопробуйте отправить ссылку заново.")

    async def show_file_format_selection(self, event):
        """Show file format selection buttons"""
        try:
            user_state = self.user_states.get(event.sender_id)
            if not user_state:
                await event.edit("❌ Сессия истекла. Отправьте ссылку заново.")
                return
            
            # Кнопки выбора формата файлов
            buttons = [
                [Button.inline("📝 TXT", data="format_txt"),
                Button.inline("📋 Markdown", data="format_md")],
                [Button.inline("📄 PDF", data="format_pdf"),
                Button.inline("📦 Все форматы", data="format_all")]
            ]
            
            await event.edit(
                f"📄 **Выберите формат файла:**\n\n🎬 **{user_state['title']}**\n👤 *{user_state['author']}*\n\nКакой формат вы предпочитаете?",
                buttons=buttons
            )
            
            # Обновляем шаг в состоянии
            user_state['step'] = 'awaiting_file_format'
            
        except Exception as e:
            logger.error(f"Error in show_file_format_selection: {e}")
            await event.edit("❌ **Произошла ошибка**\n\nПопробуйте отправить ссылку заново.")

    async def show_full_analysis_selection(self, event):
        """Show full analysis format selection"""
        try:
            user_state = self.user_states.get(event.sender_id)
            if not user_state:
                await event.edit("❌ Сессия истекла. Отправьте ссылку заново.")
                return
            
            # Кнопки выбора формата для полного анализа
            buttons = [
                [Button.inline("📋 MD + кадры", data="full_md")],
                [Button.inline("📄 PDF + кадры", data="full_pdf")],
                [Button.inline("📦 Все + кадры", data="full_all")]
            ]
            
            await event.edit(
                f"🎬 **Полный анализ с кадрами:**\n\n🎬 **{user_state['title']}**\n👤 *{user_state['author']}*\n\nВыберите формат для детального анализа видео:",
                buttons=buttons
            )
            
            # Обновляем шаг в состоянии
            user_state['step'] = 'awaiting_full_format'
            
        except Exception as e:
            logger.error(f"Error in show_full_analysis_selection: {e}")
            await event.edit("❌ **Произошла ошибка**\n\nПопробуйте отправить ссылку заново.")

    async def get_or_create_user(self, user_id: str, username: str) -> User:
        """Get existing user or create new one"""
        try:
            user = await self.db.get_user(user_id)
            if not user:
                user = await self.db.create_user(user_id, username)
            return user
        except Exception as e:
            logger.error(f"Error getting/creating user: {e}")
            raise
    
    async def download_voice_message(self, message) -> Optional[str]:
        """Download voice message from Telegram"""
        try:
            temp_dir = tempfile.mkdtemp()
            file_path = await self.client.download_media(message.voice, file=temp_dir)
            
            if file_path:
                # Convert to WAV for Whisper
                wav_path = file_path.replace('.oga', '.wav').replace('.ogg', '.wav')
                # Note: Would need pydub here for conversion
                return wav_path
            return None
            
        except Exception as e:
            logger.error(f"Error downloading voice message: {e}")
            return None
    
    async def download_audio_file(self, message, file_name: str) -> Optional[str]:
        """Download audio file from Telegram"""
        try:
            temp_dir = tempfile.mkdtemp()
            file_path = await self.client.download_media(
                message.document,
                file=os.path.join(temp_dir, file_name)
            )
            return file_path
            
        except Exception as e:
            logger.error(f"Error downloading audio file: {e}")
            return None

async def main():
    """Main entry point"""
    bot = TelegramBotService()
    await bot.start()

if __name__ == "__main__":
    asyncio.run(main())