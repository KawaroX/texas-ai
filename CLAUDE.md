# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Running the Application
- `docker-compose up --build` - Build and run all services (recommended for development)
- `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` - Run FastAPI server directly

### Task Management (Celery)
- `celery -A tasks.celery_app worker --loglevel=info &` - Start Celery worker
- `celery -A tasks.celery_app beat --loglevel=info` - Start Celery beat scheduler

### Testing
- Test scripts are located in `/scripts/` directory:
  - `scripts/test_active_interaction.py` - Test active interaction functionality
  - `scripts/test_send_image.py` - Test image sending functionality
  - `scripts/test_image_analyzer.py` - Test image analysis functionality
  - `scripts/test_proactive_image_interaction.py` - Test proactive image interactions
  - `scripts/run_interaction_test.sh` - Shell script to run interaction tests

### Development Tools Access
- API Documentation: `http://localhost:8000/docs` (FastAPI Swagger UI)
- Database Admin: `http://localhost:8080` (Adminer for PostgreSQL)
- Redis Monitor: `http://localhost:5540` (RedisInsight)
- Qdrant Vector DB: `http://localhost:6333` (Vector database dashboard)
- Mattermost Chat: `http://localhost:8065` (Chat platform frontend)

## Architecture Overview

Texas AI is an immersive AI role-playing system based on the character "Texas" from Arknights. The system features a modular architecture with memory management, emotion simulation, and active behavior systems.

### Core Directory Structure

```
app/           - Main application entry and FastAPI server
├── main.py           - FastAPI application with API endpoints
├── config.py         - Application configuration
├── life_system.py    - Life simulation system (daily routines, weather, emotions)
└── mattermost_client.py - WebSocket client for Mattermost integration

core/          - Core AI functionality
├── chat_engine.py      - LLM interaction and response generation
├── context_merger.py   - Context fusion and memory integration
├── memory_buffer.py    - Short-term memory management (2-hour cache)
├── persona.py          - Character personality and emotional state
└── rag_decision_system.py - RAG decision logic for memory retrieval

services/      - Business logic services
├── ai_service.py           - AI model integration with multiple providers
├── ai_config/              - AI provider configurations (Gemini, OpenAI, etc.)
├── ai_providers/           - AI provider implementations (Base, Gemini, OpenAI, OpenRouter)
├── memory_data_collector.py - Daily memory archival and summarization
├── memory_storage.py       - Long-term memory storage (PostgreSQL + Qdrant)
├── memory_summarizer.py    - Conversation summarization
├── life_data_service.py    - Life simulation data management
├── image_service.py        - Image processing and generation
├── image_content_analyzer.py - Image content analysis
├── image_generation_service.py - Background image generation
├── character_manager.py    - Character state and behavior management
├── scene_pre_analyzer.py   - Scene analysis for contextual responses
└── redis_cleanup_service.py - Redis cache maintenance

tasks/         - Celery background tasks
├── celery_app.py         - Celery configuration
├── daily_tasks.py        - Daily archival and cleanup tasks
├── interaction_tasks.py  - Automated interaction tasks
├── image_generation_tasks.py - Background image generation tasks
└── reporting_tasks.py    - System reporting tasks

utils/         - Utility modules
└── redis_manager.py     - Redis connection and operation utilities
```

### Key Architectural Concepts

#### Memory System (3-Layer Architecture)
1. **Buffer Memory** (`memory_buffer.py`) - Redis-cached 2-hour conversation history per channel
2. **Historical Memory** (`memory_storage.py`) - PostgreSQL permanent storage of conversation records
3. **Summary Memory** (`memory_summarizer.py` + Mem0/Qdrant) - Structured summaries for semantic search

#### Context Flow
```
User Message → Buffer Memory → Context Merger → AI Service → Persona Filter → Response
                     ↓
            Daily Collector → Historical Storage → Summary Generation → Mem0/Qdrant
```

#### AI Provider Architecture
The system supports multiple AI providers through a unified interface:
- **Base Provider** (`ai_providers/base.py`) - Abstract base class for all providers
- **Gemini Provider** (`ai_providers/gemini_provider.py`) - Google Gemini integration
- **OpenAI Provider** (`ai_providers/openai_provider.py`) - OpenAI API integration
- **OpenRouter Provider** (`ai_providers/openrouter_provider.py`) - OpenRouter API integration

#### Life System Integration
- Daily schedule simulation with weather effects
- Emotional state evolution based on interactions
- Active behavior triggers (proactive messages, mood changes)
- Time-based availability and response patterns

#### Image Processing Pipeline
- Image generation through multiple services
- Content analysis for contextual understanding
- Proactive image interactions based on conversation context
- Character-specific image generation (selfies, scenes)

### Key Configuration

#### Environment Variables (.env.template)
- Database: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
- AI Providers: `GEMINI_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`
- Mattermost: `MATTERMOST_HOST`, `MATTERMOST_TOKEN` for WebSocket integration
- Vector Search: `QDRANT_URL` for vector storage
- Weather: `HEFENG_API_KEY` for weather data integration

#### Service Dependencies
- PostgreSQL (conversations, life data)
- Redis (short-term cache, task queue)
- Qdrant (vector storage for embeddings)
- Mattermost (chat platform integration)
- Mem0 (optional external vector search service)

### Development Workflow

1. **Local Development**: Use `docker-compose up --build` for full stack
2. **Database Access**: Adminer available at `localhost:8080`
3. **Redis Monitoring**: RedisInsight at `localhost:5540`
4. **API Documentation**: FastAPI docs at `localhost:8000/docs`
5. **Vector Database**: Qdrant dashboard at `localhost:6333`

### Character Implementation Notes

Texas AI specifically embodies the Arknights character "Texas" with:
- Personality traits: calm, distant, restrained, loyal
- Language style: concise sentences, controlled emotions, subtle warmth
- World context: Penguin Logistics member, Lungmen resident, relationships with other operators
- Behavioral patterns: morning routines, task execution, weather-influenced moods

The persona system (`persona.py`) maintains emotional state consistency and ensures character-appropriate responses across all interactions.

### Image System Integration

The system includes comprehensive image processing capabilities:
- **Generation**: Multiple AI-powered image generation services
- **Analysis**: Content analysis for contextual understanding of images
- **Character Images**: Specialized selfie and character image management
- **Proactive Interactions**: AI-initiated image sharing based on context

### Testing and Debugging

Test scripts in `/scripts/` provide functionality testing:
- Active interaction testing for real-time behavior validation
- Image system testing for generation and analysis workflows
- Notification system testing for proactive message delivery
- Integration tests through shell scripts for automated validation