"""
LLM prompt builder with bilingual support.

Constructs prompts with RAG context, conversation history,
and language-specific instructions.
"""

from typing import Literal, Optional
from datetime import datetime


SYSTEM_PROMPT_TEMPLATE = """You are a helpful bilingual building navigation assistant for {building_name}.

Current Information:
- Date/Time: {datetime}
- Kiosk Location: {kiosk_location}

Building Knowledge Context:
{rag_context}

Instructions:
- Respond in the SAME LANGUAGE as the user's question
- For Japanese responses, use polite form (です・ます体)
- Provide clear, concise directions using landmarks
- Use landmark-based directions (e.g., "near the elevator") rather than cardinal directions
- If you don't know something, say so honestly
- Keep responses brief and conversational

Previous Conversation:
{conversation_history}
"""


def build_messages(
    user_text: str,
    lang: Literal["en", "ja"],
    context: str,
    history: list[dict],
    kiosk_meta: dict,
    building_name: str = "Building"
) -> list[dict]:
    """
    Build LLM prompt messages with context and history.
    
    Args:
        user_text: Current user query
        lang: Detected language
        context: RAG-retrieved context
        history: Previous conversation turns (max 10)
        kiosk_meta: Kiosk metadata (location, id)
        building_name: Name of the building
        
    Returns:
        List of message dicts for LLM
        
    Preconditions:
        - user_text is non-empty
        - lang is "en" or "ja"
        - history contains at most 10 turns
        
    Postconditions:
        - Returns valid message list
        - System message includes all context
        - User message is last in list
    """
    # Format conversation history
    history_text = ""
    for turn in history[-10:]:  # Last 10 turns only
        role = turn.get("role", "user")
        content = turn.get("content", "")
        history_text += f"{role.capitalize()}: {content}\n"
    
    if not history_text:
        history_text = "(No previous conversation)"
    
    # Build system message
    system_message = SYSTEM_PROMPT_TEMPLATE.format(
        building_name=building_name,
        datetime=datetime.now().strftime("%Y-%m-%d %H:%M"),
        kiosk_location=kiosk_meta.get("location", "Unknown"),
        rag_context=context if context else "(No relevant context found)",
        conversation_history=history_text
    )
    
    # Build message list
    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_text}
    ]
    
    return messages
