"""
MCP Server for Django LLM project.
Exposes Django database data as tools that Ollama can call.

Run this alongside Django with:
    python django_llm/mcp_server.py

Or import and use directly in views:
    from django_llm.mcp_server import MCPToolHandler
"""

import os
import sys
import json
import logging
import django
from datetime import datetime

# -------------------------
# Django setup
# Must be done before importing models
# -------------------------
# Add the project root to the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "newsite.settings")
django.setup()

from django.db.models import Sum, Max, Min, Avg
from django_llm.models import NewLLM, ConvertLLM, ReverseLLM, LLMChoice

logger = logging.getLogger(__name__)


# -------------------------
# MCP Tool Definitions
# Each tool is a function the LLM can call
# -------------------------

TOOLS = [
    {
        "name": "get_llm_entries",
        "description": "Get all LLM entries from the database including their text and date used.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of entries to return. Defaults to 10.",
                }
            },
            "required": []
        }
    },
    {
        "name": "get_voting_results",
        "description": "Get voting results for a specific LLM entry by its ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "llm_id": {
                    "type": "integer",
                    "description": "The ID of the LLM entry to get voting results for.",
                }
            },
            "required": ["llm_id"]
        }
    },
    {
        "name": "get_all_voting_results",
        "description": "Get voting results for all LLM entries in the database.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_convert_history",
        "description": "Get the history of all string conversions including input strings and character counts.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of entries to return. Defaults to 10.",
                }
            },
            "required": []
        }
    },
    {
        "name": "get_database_stats",
        "description": "Get overall statistics about the Django LLM database including counts and averages.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "search_llm_entries",
        "description": "Search for LLM entries by text content.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to find matching LLM entries.",
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_top_choices",
        "description": "Get the most voted choices across all LLM entries.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of top choices to return. Defaults to 5.",
                }
            },
            "required": []
        }
    },
]


# -------------------------
# Tool Implementations
# -------------------------

class MCPToolHandler:
    """
    Handles execution of MCP tools.
    Each method corresponds to a tool definition above.
    """

    def execute(self, tool_name: str, parameters: dict) -> dict:
        """
        Execute a tool by name with given parameters.
        Returns a dict with 'success' and either 'result' or 'error'.
        """
        handler = getattr(self, f"tool_{tool_name}", None)
        if not handler:
            return {
                "success": False,
                "error": f"Unknown tool: {tool_name}"
            }
        try:
            result = handler(**parameters)
            return {
                "success": True,
                "result": result
            }
        except Exception as e:
            logger.error(f"MCP tool '{tool_name}' failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def tool_get_llm_entries(self, limit: int = 10) -> list:
        """Get all LLM entries from the database."""
        entries = NewLLM.objects.order_by("-llm_date_used")[:limit]
        return [
            {
                "id": entry.pk,
                "text": entry.llm_text,
                "date_used": entry.llm_date_used.isoformat(),
                "was_recent": entry.was_published_recently(),
                "choice_count": entry.choices.count(),
            }
            for entry in entries
        ]

    def tool_get_voting_results(self, llm_id: int) -> dict:
        """Get voting results for a specific LLM entry."""
        try:
            entry = NewLLM.objects.get(pk=llm_id)
        except NewLLM.DoesNotExist:
            raise ValueError(f"No LLM entry found with ID {llm_id}")

        choices = entry.choices.order_by("-amount")
        total_votes = choices.aggregate(total=Sum("amount"))["total"] or 0

        return {
            "id": entry.pk,
            "text": entry.llm_text,
            "total_votes": total_votes,
            "choices": [
                {
                    "id": choice.pk,
                    "text": choice.choice_text,
                    "votes": choice.amount,
                    "percentage": round(
                        (choice.amount / total_votes * 100) if total_votes > 0 else 0, 1
                    ),
                }
                for choice in choices
            ],
            "winner": choices.first().choice_text if choices.exists() else None,
        }

    def tool_get_all_voting_results(self) -> list:
        """Get voting results for all LLM entries."""
        entries = NewLLM.objects.prefetch_related("choices").all()
        results = []
        for entry in entries:
            choices = entry.choices.order_by("-amount")
            total_votes = choices.aggregate(total=Sum("amount"))["total"] or 0
            results.append({
                "id": entry.pk,
                "text": entry.llm_text,
                "total_votes": total_votes,
                "winner": choices.first().choice_text if choices.exists() else None,
                "choice_count": choices.count(),
            })
        return results

    def tool_get_convert_history(self, limit: int = 10) -> list:
        """Get string conversion history."""
        entries = ConvertLLM.objects.order_by("-pk")[:limit]
        return [
            {
                "id": entry.pk,
                "string": entry.new_string,
                "character_count": entry.new_number,
                "word_count": len(entry.new_string.split()) if entry.new_string else 0,
            }
            for entry in entries
        ]

    def tool_get_database_stats(self) -> dict:
        """Get overall database statistics."""
        total_votes = LLMChoice.objects.aggregate(
            total=Sum("amount")
        )["total"] or 0

        avg_char_count = ConvertLLM.objects.aggregate(
            avg=Avg("new_number")
        )["avg"] or 0

        max_char_count = ConvertLLM.objects.aggregate(
            max=Max("new_number")
        )["max"] or 0

        return {
            "llm_entries": NewLLM.objects.count(),
            "total_choices": LLMChoice.objects.count(),
            "total_votes": total_votes,
            "convert_entries": ConvertLLM.objects.count(),
            "reverse_entries": ReverseLLM.objects.count(),
            "average_character_count": round(avg_char_count, 1),
            "max_character_count": max_char_count,
            "generated_at": datetime.now().isoformat(),
        }

    def tool_search_llm_entries(self, query: str) -> list:
        """Search LLM entries by text content."""
        entries = NewLLM.objects.filter(
            llm_text__icontains=query
        ).order_by("-llm_date_used")

        return [
            {
                "id": entry.pk,
                "text": entry.llm_text,
                "date_used": entry.llm_date_used.isoformat(),
                "choice_count": entry.choices.count(),
            }
            for entry in entries
        ]

    def tool_get_top_choices(self, limit: int = 5) -> list:
        """Get the most voted choices across all entries."""
        choices = LLMChoice.objects.select_related("new_llm").order_by("-amount")[:limit]
        return [
            {
                "choice_text": choice.choice_text,
                "votes": choice.amount,
                "llm_entry": choice.new_llm.llm_text,
                "llm_id": choice.new_llm.pk,
            }
            for choice in choices
        ]


# -------------------------
# MCP Server
# Runs as a standalone process
# -------------------------

class MCPServer:
    """
    Simple MCP server that listens for tool call requests
    via stdin/stdout JSON protocol.
    """

    def __init__(self):
        self.handler = MCPToolHandler()
        self.tools = TOOLS

    def handle_request(self, request: dict) -> dict:
        """Handle an incoming MCP request."""
        request_type = request.get("type")

        if request_type == "list_tools":
            return {
                "type": "tools_list",
                "tools": self.tools
            }

        elif request_type == "call_tool":
            tool_name = request.get("tool")
            parameters = request.get("parameters", {})
            result = self.handler.execute(tool_name, parameters)
            return {
                "type": "tool_result",
                "tool": tool_name,
                **result
            }

        else:
            return {
                "type": "error",
                "error": f"Unknown request type: {request_type}"
            }

    def run(self):
        """Run the MCP server, reading from stdin and writing to stdout."""
        logger.info("MCP Server started. Listening for requests...")
        print(json.dumps({"type": "ready", "tools": len(self.tools)}), flush=True)

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                response = self.handle_request(request)
                print(json.dumps(response), flush=True)
            except json.JSONDecodeError as e:
                print(json.dumps({
                    "type": "error",
                    "error": f"Invalid JSON: {e}"
                }), flush=True)
            except Exception as e:
                logger.error(f"MCP server error: {e}")
                print(json.dumps({
                    "type": "error",
                    "error": str(e)
                }), flush=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    server = MCPServer()
    server.run()