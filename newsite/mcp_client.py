"""
MCP Client for Django LLM views.
Connects Django views to the MCP server and Ollama.

Usage in views:
    from django_llm.mcp_client import MCPOllamaClient

    client = MCPOllamaClient()
    response = client.chat_with_tools("Summarise the voting results for entry 1")
"""

import json
import logging
import subprocess
import os
import sys

logger = logging.getLogger(__name__)

# Import ollama safely
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    ollama = None
    OLLAMA_AVAILABLE = False

# Import tool handler directly for in-process use
# This avoids needing a separate MCP server process
try:
    from django_llm.mcp_server import MCPToolHandler, TOOLS
    MCP_AVAILABLE = True
except Exception as e:
    logger.warning(f"MCP tools unavailable: {e}")
    MCPToolHandler = None
    TOOLS = []
    MCP_AVAILABLE = False


class MCPOllamaClient:
    """
    Combines Ollama LLM with MCP tools.
    Allows Ollama to call Django database tools when answering questions.
    """

    def __init__(self, model: str = "llama3"):
        self.model = model
        self.tool_handler = MCPToolHandler() if MCP_AVAILABLE else None
        self.tools = TOOLS

    def _format_tools_for_ollama(self) -> list:
        """Format MCP tools into Ollama tool format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                }
            }
            for tool in self.tools
        ]

    def _execute_tool(self, tool_name: str, parameters: dict) -> str:
        """Execute an MCP tool and return the result as a string."""
        if not self.tool_handler:
            return json.dumps({"error": "MCP tools unavailable"})

        result = self.tool_handler.execute(tool_name, parameters)
        return json.dumps(result.get("result", result.get("error", "No result")))

    def chat_with_tools(self, prompt: str, max_iterations: int = 5) -> str:
        """
        Send a prompt to Ollama with MCP tools available.
        Ollama can call tools to fetch data before responding.

        Args:
            prompt: The user's question or request
            max_iterations: Max tool call loops to prevent infinite loops

        Returns:
            The final text response from Ollama
        """
        if not OLLAMA_AVAILABLE:
            return "Ollama is not available. Please install and start it."

        if not MCP_AVAILABLE:
            # Fall back to plain Ollama without tools
            return self._plain_chat(prompt)

        messages = [{"role": "user", "content": prompt}]
        tools = self._format_tools_for_ollama()

        for iteration in range(max_iterations):
            try:
                response = ollama.chat(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    options={"num_predict": 500}
                )

                message = response["message"]

                # If no tool calls, return the final response
                if not message.get("tool_calls"):
                    return message.get("content", "No response generated.")

                # Process tool calls
                messages.append(message)

                for tool_call in message["tool_calls"]:
                    tool_name = tool_call["function"]["name"]
                    parameters = tool_call["function"]["arguments"]

                    logger.debug(f"Ollama calling tool: {tool_name} with {parameters}")

                    # Execute the tool
                    tool_result = self._execute_tool(tool_name, parameters)

                    logger.debug(f"Tool result: {tool_result[:200]}")

                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "content": tool_result,
                    })

            except Exception as e:
                logger.error(f"MCPOllamaClient error on iteration {iteration}: {e}")
                return f"Error communicating with LLM: {str(e)}"

        return "Maximum tool call iterations reached. Please try a more specific question."

    def _plain_chat(self, prompt: str) -> str:
        """Fall back to plain Ollama chat without tools."""
        try:
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                options={"num_predict": 300}
            )
            return response["message"]["content"]
        except Exception as e:
            logger.error(f"Plain Ollama chat error: {e}")
            return f"LLM error: {str(e)}"

    def summarise_convert(self, input_str: str) -> str:
        """Summarise a converted string using Ollama with database context."""
        prompt = (
            f"Please analyse the following text and provide a brief summary "
            f"of its content, tone, and key points in 2-3 sentences. "
            f"You can also use the get_convert_history tool to compare it "
            f"with previous entries if relevant:\n\n{input_str}"
        )
        return self.chat_with_tools(prompt)

    def summarise_voting_results(self, llm_id: int, llm_text: str) -> str:
        """Summarise voting results for a specific LLM entry."""
        prompt = (
            f"Use the get_voting_results tool with llm_id={llm_id} to fetch "
            f"the voting results for '{llm_text}', then provide a brief 2-3 sentence "
            f"summary highlighting the most popular choice and any notable patterns."
        )
        return self.chat_with_tools(prompt)

    def get_database_overview(self) -> str:
        """Get a natural language overview of the entire database."""
        prompt = (
            "Use the get_database_stats tool and get_all_voting_results tool "
            "to give me a concise overview of all the data in the Django LLM "
            "database. Summarise the key statistics and any interesting patterns."
        )
        return self.chat_with_tools(prompt)