"""
LLM tool definitions for function calling.

Defines web search tool schema for LLM integration.
"""

# Web search tool definition for LLM function calling
WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current information not available in the building knowledge base. Use this when the user asks about topics beyond building navigation.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to execute"
                }
            },
            "required": ["query"]
        }
    }
}

# List of all available tools
AVAILABLE_TOOLS = [WEB_SEARCH_TOOL]
