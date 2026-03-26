"""
Centralised prompt templates for Ollama calls.
Edit these to tune LLM behaviour without touching view logic.
"""

CONVERT_SUMMARY_PROMPT = (
    "Please analyse the following text and provide a brief summary "
    "of its content, tone, and key points in 2-3 sentences. "
    "You can also use the get_convert_history tool to compare it "
    "with previous entries if relevant:\n\n{text}"
)

RESULTS_SUMMARY_PROMPT = (
    "The following are the voting results for '{title}':\n\n"
    "{results}\n\n"
    "Please provide a brief 2-3 sentence summary of these results, "
    "highlighting the most popular choice and any notable patterns."
)

REVERSE_SUMMARY_PROMPT = (
    "The number {number} corresponds to the string '{string}'. "
    "Please provide a brief analysis of what this data might represent "
    "and any interesting observations about it."
)

DATABASE_OVERVIEW_PROMPT = (
    "Use the get_database_stats tool and get_all_voting_results tool "
    "to give me a concise overview of all the data in the Django LLM "
    "database. Summarise the key statistics and any interesting patterns."
)

CHAT_SYSTEM_PROMPT = (
    "You are a helpful AI assistant with access to a Django database. "
    "You can use tools to query LLM entries, voting results, "
    "conversion history, and database statistics. "
    "Always use the available tools to fetch real data when answering "
    "questions about the database content. "
    "Be concise and helpful in your responses."
)
