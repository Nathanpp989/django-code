"""
MCP Client for Django LLM views.
Connects Django views to the MCP server and Ollama.
Supports both single-turn and multi-turn conversations with tool use.
"""

import json
import logging

logger = logging.getLogger(__name__)

# Import ollama safely
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    ollama = None
    OLLAMA_AVAILABLE = False

# Import tool handler directly for in-process use
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
    Supports single-turn prompts and full multi-turn conversations.
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

    def _run_tool_loop(
        self,
        messages: list,
        max_iterations: int = 5
    ) -> str:
        """
        Core tool-calling loop.
        Sends messages to Ollama, handles tool calls,
        and returns the final text response.
        """
        tools = self._format_tools_for_ollama()

        for iteration in range(max_iterations):
            try:
                response = ollama.chat(
                    model=self.model,
                    messages=messages,
                    tools=tools if MCP_AVAILABLE else None,
                    options={"num_predict": 500}
                )

                message = response["message"]

                # No tool calls means we have a final response
                if not message.get("tool_calls"):
                    return message.get("content", "No response generated.")

                # Append assistant message with tool calls
                messages.append(message)

                # Process each tool call
                for tool_call in message["tool_calls"]:
                    tool_name = tool_call["function"]["name"]
                    parameters = tool_call["function"]["arguments"]

                    logger.debug(f"Ollama calling tool: {tool_name} with {parameters}")
                    tool_result = self._execute_tool(tool_name, parameters)
                    logger.debug(f"Tool result: {tool_result[:200]}")

                    messages.append({
                        "role": "tool",
                        "content": tool_result,
                    })

            except Exception as e:
                logger.error(f"Tool loop error on iteration {iteration}: {e}")
                return f"Error communicating with LLM: {str(e)}"

        return "Maximum tool call iterations reached. Please try a more specific question."

    def chat_with_tools(self, prompt: str, max_iterations: int = 5) -> str:
        """
        Single-turn chat with MCP tools available.
        Used by convert and results views.
        """
        if not OLLAMA_AVAILABLE:
            return "Ollama is not available. Please install and start it."

        messages = [{"role": "user", "content": prompt}]
        return self._run_tool_loop(messages, max_iterations)

    def chat_with_tools_and_history(
        self,
        messages: list,
        system: str = None,
        max_iterations: int = 5
    ) -> str:
        """
        Multi-turn chat with full conversation history and MCP tools.
        Used by the chat interface view.

        Args:
            messages: Full conversation history as list of
                      {"role": "user"/"assistant", "content": "..."} dicts
            system: Optional system prompt
            max_iterations: Max tool call loops

        Returns:
            AI response text
        """
        if not OLLAMA_AVAILABLE:
            return "Ollama is not available. Please install and start it."

        # Build messages with optional system prompt
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        return self._run_tool_loop(full_messages, max_iterations)

    def _plain_chat(self, prompt: str) -> str:
        """Fallback plain Ollama chat without tools."""
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
        """Summarise a converted string with database context."""
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
