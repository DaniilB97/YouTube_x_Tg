# 🤖 YouTube Summarizer Bot - Microservices Architecture

> **Advanced AI-powered YouTube video analysis and summarization platform with interactive chat capabilities**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=flat&logo=docker&logoColor=white)](https://www.docker.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Telegram](https://img.shields.io/badge/Telegram-2CA5E0?style=flat&logo=telegram&logoColor=white)](https://telegram.org/)
[![Redis](https://img.shields.io/badge/redis-%23DD0031.svg?style=flat&logo=redis&logoColor=white)](https://redis.io/)
[![Supabase](https://img.shields.io/badge/Supabase-3ECF8E?style=flat&logo=supabase&logoColor=white)](https://supabase.com/)

## 🌟 Features

### 📹 **Video Analysis**
- **Smart Content Recognition**: Automatic extraction of YouTube video transcripts
- **Multi-format Output**: Generate summaries in TXT, Markdown, and PDF formats
- **Visual Frame Analysis**: Extract and analyze key video frames with AI-powered scene detection
- **Real-time Progress**: Beautiful progress bars with time estimates during processing

### 🎬 **Advanced Video Processing**
- **Full Video Analysis**: Comprehensive reports combining audio transcripts with visual content analysis
- **Scene Detection**: Intelligent extraction of key frames using computer vision
- **Visual Context Integration**: AI analysis of charts, presentations, and visual elements
- **Multi-language Support**: Process videos in multiple languages with automatic detection
- **Voice Overdubbing**: AI-powered voice replacement and lip-sync for multilingual content creation

### 🤖 **AI-Powered Intelligence**
- **Dual AI System**: Primary Gemini integration with Ollama fallback for maximum reliability
- **Interactive Chat**: Discuss video content with AI that remembers context and conversation history
- **Smart Summarization**: Generate short, medium, and detailed summaries tailored to your needs
- **Visual Content Understanding**: AI analysis of charts, graphs, and presentation slides
- **Voice Synthesis**: Advanced text-to-speech with voice cloning capabilities
- **Multilingual Overdubbing**: Replace original audio with AI-generated voices in different languages

### 💬 **Interactive User Experience**
- **Telegram Bot Interface**: Intuitive menu system with persistent keyboard shortcuts
- **Real-time Feedback**: Live progress updates and processing status
- **Chat Memory**: AI remembers your video discussions and preferences
- **Rating System**: Built-in feedback collection with star ratings and comments
- **User Management**: Comprehensive user profiles and preferences stored in Supabase
- **Usage Analytics**: Track processing history and user engagement metrics

### 🏗️ **Microservices Architecture**
- **Scalable Design**: Independent services for video processing, AI analysis, and file generation
- **High Availability**: Built-in failover mechanisms and error recovery
- **Queue Management**: Redis-based task queuing for reliable processing
- **Docker Containerization**: Easy deployment and scaling

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- Telegram Bot Token
- Google Gemini API Key (recommended)
- Supabase Account (Database & Authentication)
- Optional: Ollama for local AI models

### 1. Clone Repository
```bash
git clone https://github.com/your-username/youtube-summarizer-microservices.git
cd youtube-summarizer-microservices
```

### 2. Environment Setup
```bash
cp .env.example .env
# Edit .env with your credentials
```

### 3. Launch Services
```bash
docker compose up -d
```

### 4. Start Chatting!
Send `/start` to your Telegram bot and begin analyzing YouTube videos!

## 📋 Environment Variables

Create a `.env` file with the following variables:

```env
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_API_ID=your_telegram_api_id
TELEGRAM_API_HASH=your_telegram_api_hash

# AI Services
GEMINI_API_KEY=your_gemini_api_key

# Database & Authentication
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_anon_key
SUPABASE_SERVICE_KEY=your_supabase_service_role_key

# Optional: Ollama Configuration
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=llama3.1:latest
```

## 🎯 How It Works

### 1. **Send YouTube Link**
Simply send any YouTube URL to the bot via Telegram

### 2. **Choose Processing Type**
- **📝 Text Only**: Quick transcript and summary
- **📄 Files**: Generate downloadable documents
- **🎬 Full Analysis**: Complete video analysis with visual content

### 3. **Select Output Format**
- **TXT**: Plain text format
- **Markdown**: Formatted with headers and structure
- **PDF**: Professional document with embedded images
- **All Formats**: Receive all three file types

### 4. **Get Results**
Receive comprehensive analysis including:
- Video transcript
- AI-generated summaries (short, medium, detailed)
- Key video frames with context
- Visual content analysis
- Downloadable files

### 5. **Interactive Discussion**
Use the "💬 Discuss Video" feature to:
- Ask questions about the content
- Get clarifications on specific topics
- Explore deeper insights with AI chat

## 🔧 Services

### **API Gateway**
- Request routing and validation
- Rate limiting and authentication
- Health checks and monitoring

### **Video Processor** 
- YouTube video downloading and analysis
- Frame extraction and scene detection
- Transcript API integration

### **Audio Processor**
- Whisper AI transcription
- Audio format conversion
- Voice processing capabilities
- Text-to-speech synthesis
- Voice cloning and overdubbing
- Multilingual voice generation

### **AI Processor**
- Gemini/Ollama integration
- Summary generation
- Visual content analysis
- Interactive chat processing

### **File Manager**
- Multi-format document generation
- Image embedding in PDFs
- File storage and delivery

### **Telegram Bot**
- User interface and interaction
- Real-time progress updates
- Chat memory and context management
- User authentication via Supabase
- Persistent user preferences and history

## 🗃️ Database Schema (Supabase)

### **Users Table**
```sql
CREATE TABLE users (
  user_id UUID PRIMARY KEY,
  telegram_id BIGINT UNIQUE,
  username VARCHAR(255),
  language VARCHAR(10) DEFAULT 'en',
  subscription_tier VARCHAR(50) DEFAULT 'free',
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
```

### **Video Summaries Table**
```sql
CREATE TABLE video_summaries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(user_id),
  video_id VARCHAR(255),
  title TEXT,
  summary_short TEXT,
  summary_medium TEXT,
  summary_detailed TEXT,
  processing_type VARCHAR(50),
  file_paths JSONB,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### **User Feedback Table**
```sql
CREATE TABLE user_feedback (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(user_id),
  rating INTEGER CHECK (rating >= 1 AND rating <= 5),
  comment TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### 📄 **PDF Report**
- Professional document layout
- Embedded video frames
- Structured summaries
- Visual content analysis
- Timestamp references

### 📝 **Markdown File**
```markdown
# Video Title

## 🎬 Video Frames

### Frame 1 - 02:15
![Frame 1](frame_001.jpg)
**Context:** Speaker explains the main concept...

### Frame 2 - 05:42  
![Frame 2](frame_002.jpg)
**Context:** Chart showing research results...
```

### 📋 **TXT Format**
```
FRAME 1 - 02:15
File: frame_001.jpg
Context: Speaker explains the main concept...

FRAME 2 - 05:42
File: frame_002.jpg  
Context: Chart showing research results...
```

## 💬 Interactive Chat Features

## 📊 File Output Examples
- Ask questions about video content
- Get clarifications on specific topics
- Explore related concepts

### **Context Memory**
- AI remembers your video discussions
- Maintains conversation history
- Personalized responses based on your interests

### **Smart Responses**
- Natural language understanding
- Context-aware answers
- Follow-up question suggestions

## 📈 Monitoring & Analytics

### **Built-in Metrics**
- Processing time tracking
- Success/failure rates
- User engagement statistics
- Performance monitoring

### **Health Checks**
- Service availability monitoring
- Automatic failover
- Error recovery mechanisms

### **Logging**
- Comprehensive request logging
- Error tracking and alerting
- Performance analytics

## 🔒 Security & Privacy

### **Data Protection**
- Temporary file cleanup
- Secure credential management
- Privacy-first design

### **Rate Limiting**
- Per-user request limits
- API protection
- Resource management

### **Authentication**
- Secure Telegram integration
- User verification
- Access control

## 🚀 Deployment

### **Development**
```bash
docker compose up -d
```

### **Production**
```bash
docker compose -f docker-compose.prod.yml up -d
```

### **Scaling**
```bash
docker compose up -d --scale ai-processor=3 --scale video-processor=2
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License
## 🙏 Acknowledgments

- **OpenAI Whisper** for audio transcription
- **Google Gemini** for AI-powered analysis
- **Ollama** for local AI model support
- **yt-dlp** for YouTube video processing
- **ReportLab** for PDF generation
- **OpenCV** for computer vision capabilities
- **Supabase** for database and authentication services
- **ElevenLabs/Coqui TTS** for voice synthesis and cloning

## 📞 Support

- 🐛 **Bug Reports**: [GitHub Issues](https://github.com/your-username/youtube-summarizer-microservices/issues)
- 💬 **Discussions**: [GitHub Discussions](https://github.com/your-username/youtube-summarizer-microservices/discussions)
- 📧 **Email**: support@yourdomain.com

---

<div align="center">

**⭐ Star this repository if you found it helpful!**

Made with ❤️ using modern microservices architecture

</div>