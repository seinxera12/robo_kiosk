# Enhanced Terminal Logging & Telemetry

This document describes the enhanced logging system for the voice chatbot pipeline, providing rich terminal telemetry for debugging and monitoring.

## Overview

The logging system now provides detailed, structured output for:
- Intent classification and routing decisions
- Query reformulation process (for search queries)
- Context retrieval (RAG or web search)
- LLM prompt construction
- LLM generation metrics
- Search results and formatting

## Log Sections

### 1. Intent Classification & Routing

```
================================================================================
🎯 INTENT CLASSIFICATION
================================================================================
📝 User input: 'What's the weather like in Tokyo?'
🌐 Language: en
🔍 Intent: SEARCH
📊 Confidence: 87.50%
🔧 Method: embedding
🎯 Routing: Web search via SearXNG + query reformulation
================================================================================
```

**Fields:**
- User input (verbatim transcript)
- Detected language
- Classified intent (BUILDING/SEARCH/GENERAL)
- Confidence score
- Classification method (embedding/keyword/fallback)
- Routing decision explanation

---

### 2. Query Reformulation (Search Intent Only)

```
================================================================================
🔍 QUERY REFORMULATION START
================================================================================
📝 Original user message: 'What's the weather like in Tokyo?'
📊 Message length: 35 characters
📚 Conversation history: 4 messages (max 6)
   Recent context:
   👤 user: Can you help me with something?
   🤖 assistant: Of course! What would you like to know?
🌐 Language detected: English
📋 Prompt type: Extraction
💬 Total messages in context: 6 (1 system + 4 history + 1 current)
🤖 Calling Ollama model: qwen2.5:3b
⚙️  Model settings: temperature=0, max_tokens=32, stream=False
🌐 Ollama endpoint: http://localhost:11434/api/chat
⏱️  Ollama call completed in 0.87s
────────────────────────────────────────────────────────────────────────────────
✅ REFORMULATION SUCCESS
📤 Reformulated query: 'tokyo weather forecast'
📏 Query length: 22 characters
⏱️  Total duration: 0.89s
🔄 Transformation applied:
   Before: 'What's the weather like in Tokyo?'
   After:  'tokyo weather forecast'
================================================================================
```

**Fields:**
- Original user message
- Message length
- Conversation history context (last 3 turns shown)
- Language detection (English vs Japanese)
- Prompt type (Extraction vs Translation+Extraction)
- Total context messages
- Model and settings
- Ollama endpoint
- Call duration
- Reformulated query
- Transformation comparison

**Japanese Example:**
```
🌐 Language detected: Japanese (日本語)
📋 Prompt type: Translation + Extraction
```

**Fallback Example:**
```
────────────────────────────────────────────────────────────────────────────────
⚠️  REFORMULATION FAILED: ConnectError: Connection refused
🔄 Falling back to original input: 'What's the weather like in Tokyo?'
================================================================================
```

---

### 3. Context Retrieval

#### 3a. RAG Retrieval (Building Intent)

```
────────────────────────────────────────────────────────────────────────────────
📚 CONTEXT RETRIEVAL
────────────────────────────────────────────────────────────────────────────────
🏢 Retrieving from building knowledge base (RAG)...
   Query: 'Where is the cafeteria?'
   Language: en
   Top-K: 3 chunks
✅ RAG retrieval complete: 847 characters
   Preview: The cafeteria is located on the 2nd floor of Building A, near the main elevator bank. It is open from 7:00 AM to 7:00 PM on weekdays...
================================================================================
```

#### 3b. Web Search (Search Intent)

```
────────────────────────────────────────────────────────────────────────────────
🌐 WEB SEARCH
────────────────────────────────────────────────────────────────────────────────
🔍 Search query: 'tokyo weather forecast'
🌐 Search engine: SearXNG (http://localhost:8080)
📊 Max results: 3
🌐 Language: en
✅ Search complete: 3 results returned
────────────────────────────────────────────────────────────────────────────────
📄 SEARCH RESULTS
────────────────────────────────────────────────────────────────────────────────
Result #1:
  📌 Title: Tokyo Weather Forecast - Japan Meteorological Agency
  📝 Content: Current weather in Tokyo: Partly cloudy, 18°C. Tomorrow: Sunny with highs of 22°C. Extended forecast shows clear skies through the weekend...
  🔗 URL: https://www.jma.go.jp/en/tokyo
  ────────────────────────────────────────────────────────────────────────────
Result #2:
  📌 Title: Tokyo 7-Day Weather Forecast
  📝 Content: Detailed 7-day forecast for Tokyo, Japan. Today: 18°C, partly cloudy. Tomorrow: 22°C, sunny. Wednesday: 20°C, light rain expected...
  🔗 URL: https://weather.com/tokyo
  ────────────────────────────────────────────────────────────────────────────
Result #3:
  📌 Title: Real-time Tokyo Weather Updates
  📝 Content: Live weather updates for Tokyo metropolitan area. Current conditions, hourly forecasts, and weather alerts...
  🔗 URL: https://weathernews.jp/tokyo
────────────────────────────────────────────────────────────────────────────────
✅ Search context formatted: 1243 characters
================================================================================
```

#### 3c. General Conversation (No Context)

```
────────────────────────────────────────────────────────────────────────────────
📚 CONTEXT RETRIEVAL
────────────────────────────────────────────────────────────────────────────────
💬 No external context (general conversation mode)
================================================================================
```

---

### 4. Prompt Construction

```
────────────────────────────────────────────────────────────────────────────────
🔨 PROMPT CONSTRUCTION
────────────────────────────────────────────────────────────────────────────────
✅ Prompt built successfully
   Intent: SEARCH
   Total messages: 5
   Context length: 1243 characters
   History turns: 2
   Total prompt size: 2847 characters (~711 tokens)
────────────────────────────────────────────────────────────────────────────────
📋 PROMPT PREVIEW
────────────────────────────────────────────────────────────────────────────────
🤖 Message 1 (system, 456 chars):
   You are a helpful voice assistant at a building kiosk. Answer questions about the building, provide directions, and help with general inquiries. Be concise...
👤 Message 2 (user, 35 chars):
   Can you help me with something?
💬 Message 3 (assistant, 42 chars):
   Of course! What would you like to know?
👤 Message 4 (user, 35 chars):
   What's the weather like in Tokyo?
🤖 Message 5 (system, 1243 chars):
   Based on the following search results:

   Result 1: Tokyo Weather Forecast - Japan Meteorological Agency
   Current weather in Tokyo: Partly cloudy, 18°C. Tomorrow: Sunny with highs...
================================================================================
```

**Fields:**
- Intent used for prompt
- Total messages in prompt
- Context length
- Number of conversation history turns
- Total prompt size (characters and estimated tokens)
- Preview of each message (first 150 chars)

---

### 5. LLM Generation

```
🤖 LLM GENERATION START
────────────────────────────────────────────────────────────────────────────────
[Streaming tokens in real-time...]
────────────────────────────────────────────────────────────────────────────────
✅ LLM GENERATION COMPLETE
   Response length: 287 characters
   Tokens generated: 64
   Duration: 3.42s
   Speed: 18.7 tokens/sec
   Preview: Based on the current weather data, Tokyo is experiencing partly cloudy conditions with a temperature of 18°C. Tomorrow...
================================================================================
```

**Fields:**
- Response length (characters)
- Tokens generated (count)
- Generation duration
- Generation speed (tokens/sec)
- Response preview (first 100 chars)

---

## Log Levels

The enhanced logging uses the following levels:

- **INFO**: Normal operation, telemetry, metrics
- **WARNING**: Fallbacks, degraded operation, recoverable errors
- **ERROR**: Failures, exceptions (not shown in examples above)
- **DEBUG**: Detailed internal state (disabled by default)

## Visual Elements

The logging uses Unicode characters for visual clarity:

- **Separators**: `═` (80 chars) for major sections, `─` (80 chars) for subsections
- **Icons**: 
  - 🎯 Intent classification
  - 🔍 Search/query reformulation
  - 🏢 Building/RAG
  - 💬 General conversation
  - 📝 Text/input
  - 🌐 Language/web
  - 📊 Metrics/stats
  - ⚙️ Settings/config
  - ⏱️ Timing
  - ✅ Success
  - ⚠️ Warning
  - ❌ Error
  - 🔄 Transformation
  - 📚 Context
  - 🔨 Construction
  - 🤖 AI/LLM/system
  - 👤 User
  - 📌 Title
  - 🔗 Link
  - 📄 Document/results

## Example Full Flow (Search Query)

```
================================================================================
🎯 INTENT CLASSIFICATION
================================================================================
📝 User input: 'What's the weather like in Tokyo?'
🌐 Language: en
🔍 Intent: SEARCH
📊 Confidence: 87.50%
🔧 Method: embedding
🎯 Routing: Web search via SearXNG + query reformulation
================================================================================
────────────────────────────────────────────────────────────────────────────────
📚 CONTEXT RETRIEVAL
────────────────────────────────────────────────────────────────────────────────
🔍 Initiating web search pipeline...
================================================================================
🔍 QUERY REFORMULATION START
================================================================================
📝 Original user message: 'What's the weather like in Tokyo?'
📊 Message length: 35 characters
📚 Conversation history: 0 messages (max 6)
🌐 Language detected: English
📋 Prompt type: Extraction
💬 Total messages in context: 2 (1 system + 0 history + 1 current)
🤖 Calling Ollama model: qwen2.5:3b
⚙️  Model settings: temperature=0, max_tokens=32, stream=False
🌐 Ollama endpoint: http://localhost:11434/api/chat
⏱️  Ollama call completed in 0.87s
────────────────────────────────────────────────────────────────────────────────
✅ REFORMULATION SUCCESS
📤 Reformulated query: 'tokyo weather forecast'
📏 Query length: 22 characters
⏱️  Total duration: 0.89s
🔄 Transformation applied:
   Before: 'What's the weather like in Tokyo?'
   After:  'tokyo weather forecast'
================================================================================
────────────────────────────────────────────────────────────────────────────────
🌐 WEB SEARCH
────────────────────────────────────────────────────────────────────────────────
🔍 Search query: 'tokyo weather forecast'
🌐 Search engine: SearXNG (http://localhost:8080)
📊 Max results: 3
🌐 Language: en
✅ Search complete: 3 results returned
────────────────────────────────────────────────────────────────────────────────
📄 SEARCH RESULTS
────────────────────────────────────────────────────────────────────────────────
Result #1:
  📌 Title: Tokyo Weather Forecast
  📝 Content: Current weather in Tokyo: Partly cloudy, 18°C...
  🔗 URL: https://weather.com/tokyo
────────────────────────────────────────────────────────────────────────────────
✅ Search context formatted: 1243 characters
================================================================================
────────────────────────────────────────────────────────────────────────────────
🔨 PROMPT CONSTRUCTION
────────────────────────────────────────────────────────────────────────────────
✅ Prompt built successfully
   Intent: SEARCH
   Total messages: 2
   Context length: 1243 characters
   History turns: 0
   Total prompt size: 1699 characters (~424 tokens)
────────────────────────────────────────────────────────────────────────────────
📋 PROMPT PREVIEW
────────────────────────────────────────────────────────────────────────────────
🤖 Message 1 (system, 456 chars):
   You are a helpful voice assistant...
👤 Message 2 (user, 35 chars):
   What's the weather like in Tokyo?
================================================================================
🤖 LLM GENERATION START
────────────────────────────────────────────────────────────────────────────────
────────────────────────────────────────────────────────────────────────────────
✅ LLM GENERATION COMPLETE
   Response length: 287 characters
   Tokens generated: 64
   Duration: 3.42s
   Speed: 18.7 tokens/sec
   Preview: Based on the current weather data, Tokyo is experiencing...
================================================================================
```

## Benefits

1. **Debugging**: Easy to trace the flow of a request through the pipeline
2. **Performance Monitoring**: Timing metrics for each stage
3. **Quality Assurance**: See exactly what context and prompts are being used
4. **Troubleshooting**: Clear error messages with fallback behavior
5. **Transparency**: Understand routing decisions and transformations
6. **Metrics**: Token counts, speeds, and sizes for optimization

## Configuration

Logging level can be configured in the application startup. The enhanced telemetry uses the standard Python `logging` module at INFO level.

To see all telemetry:
```python
logging.basicConfig(level=logging.INFO)
```

To reduce verbosity:
```python
logging.basicConfig(level=logging.WARNING)
```

To see internal details:
```python
logging.basicConfig(level=logging.DEBUG)
```
