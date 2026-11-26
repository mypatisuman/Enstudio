import logging
import os
import sys
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from domain.chat.services.chat_memory_service import _notify_failure, _get_full_conversation_context, _add_to_chat_memory, _clear_chat_history
from common.ai.rag.chat_rag import query_chat_rag
from common.services.agentic_integration import run_route_classifier
from common.ai.llm import get_flash_llm, get_flash_with_search

logger = logging.getLogger(__name__)


# ============================================================================
# CONVERSATION HISTORY MANAGEMENT - Uses Central Unlimited Memory
# ============================================================================

from common.ai.memory import (
    add_conversation_turn,
    format_conversation_for_prompt,
    get_full_conversation_history,
)


# ============================================================================
# CHAT PROCESSING (LLM with Web Search)
# ============================================================================
def _load_chat_response_prompt() -> str:
    """Load the chat response prompt from the markdown file."""
    prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts', 'chat_agent.md')
    try:
        with open(prompt_path, encoding='utf-8') as f:
            content = f.read()
            # Extract only the response formatting part (skip the classification part)
            if "## PART 2: RESPONSE FORMATTING RULES" in content:
                return content.split("## PART 2: RESPONSE FORMATTING RULES")[1]
            elif "RESPONSE FORMATTING RULES:" in content:
                return content.split("RESPONSE FORMATTING RULES:")[1]
            return content
    except FileNotFoundError:
        logger.error(f"[CHAT_AGENT] Prompt file not found at {prompt_path}")
        return ""


def _process_chat_query(user_query: str, session_id: str, user_id: int | None = None) -> dict[str, Any]:
    """
    Process user query using LLM with web search and COMPLETE conversation context.
    Handles vendor queries, comparisons, specifications, etc.
    """
    logger.info(f"[CHAT_AGENT] Processing query: {user_query}")

    try:
        # Initialize LLM with native web search enabled
        llm = get_flash_with_search(temperature=0.1)

        # 🔧 NEW: Get COMPLETE conversation history (unlimited)
        conversation_context = _get_full_conversation_context(session_id)
        logger.info(f"[CHAT_AGENT] Processing with {len(conversation_context)} chars of history")

        # Load response formatting prompt
        response_prompt = _load_chat_response_prompt()

        # 🔧 NEW: Escape braces in history context for template rendering
        history_context = conversation_context.replace("{", "{{").replace("}", "}}")

        # Combine prompt with COMPLETE history and query
        full_prompt = f"{response_prompt}\n{history_context}\n\nUser Question: {{query}}"

        prompt_template = ChatPromptTemplate.from_template(full_prompt)

        # Invoke LLM with complete context
        chain = prompt_template | llm | StrOutputParser()
        answer = chain.invoke({"query": user_query})

        logger.info(f"[CHAT_AGENT] Generated response ({len(answer)} chars) with complete context")

        # Return Response (memory storage handled by process_chat_request)
        return {
            "answer": answer,
            "source": "llm_web_search_with_context",
            "query_intent": "general_info",
            "original_query": user_query
        }

    except Exception as e:
        logger.exception(f"[CHAT_AGENT] Error generating response: {e}")

        # Notify admin
        _notify_failure("Chat Response Generation",
            f"Error generating chat response: {str(e)}",
            user_id=user_id, user_query=user_query[:200])

        return {
            "answer": "I apologize, but I encountered an error processing your request.",
            "source": "error",
            "error": str(e)
        }


# ============================================================================
# COMBINED LLM CLASSIFICATION (Intent + Follow-up in ONE call)
# ============================================================================
def _classify_chat_query_combined(user_query: str, conversation_context: str) -> str:
    """
    COMBINED classification: Intent (VALID/INVALID) + Follow-up detection in ONE LLM call.

    This replaces two separate LLM calls with a single call for efficiency.

    Returns:
        "VALID_FOLLOWUP" - Valid chat query, can answer from conversation history only
        "VALID_NEW_QUERY" - Valid chat query, needs database search
        "INVALID" - Not a chat query, needs routing to another page

    Args:
        user_query: Current user question
        conversation_context: Full conversation history
    """
    try:
        llm = get_flash_llm(temperature=0.1)

        # Check if we have conversation history
        has_history = conversation_context and len(conversation_context.strip()) >= 50

        # Validate conversation has meaningful content (not just greetings)
        has_vendor_data = False
        if has_history:
            # Quick check: does conversation mention vendors or products?
            context_lower = conversation_context.lower()
            vendor_keywords = ['vendor', 'emerson', 'abb', 'honeywell', 'siemens', 'yokogawa',
                              'endress', 'hauser', 'wika', 'rosemount', 'fisher',
                              'pressure', 'temperature', 'flow', 'transmitter', 'sensor',
                              'valve', 'meter', 'gauge', 'controller', 'analyzer']

            has_vendor_data = any(keyword in context_lower for keyword in vendor_keywords)

            if not has_vendor_data:
                logger.info("[CHAT_AGENT] Conversation has no vendor/product data, treating as no history")
                has_history = False

        prompt_template = """You are a query classifier for an industrial automation chat system.

CONVERSATION HISTORY:
{conversation_context}

CURRENT USER QUERY:
{query}

TASK:
Classify this query into ONE of three categories by reasoning through these steps:

## STEP 1: UNDERSTAND THE USER (Critical - Reason First)

Before classifying, analyze these questions:

**A. What is the user literally asking?**
   - Read the EXACT words in the query
   - Identify KEY VERBS: "tell me", "what are", "which", "compare", "explain", "show me", etc.
   - Identify WHAT INFORMATION they want (vendors? models? specs? comparison? explanation?)

**B. Can this question be answered from the CONVERSATION HISTORY?**

   Think step-by-step:
   1. Look at the conversation history above
   2. Identify what INFORMATION is actually present in the history
   3. Check: Does the history contain the SPECIFIC INFORMATION the user is asking for?

   Examples:
   - History says: "Vendors: ABB, Emerson, Honeywell"
     * Information available: Just vendor names
     * NOT available: models, specs, features, prices, certifications, etc.

   - History says: "ABB offers 2600T and 2700T series with HART protocol. Emerson offers 3051 series with SIL 2 rating."
     * Information available: Vendor names, model series, some features (HART, SIL)
     * NOT available: prices, detailed specs, certifications, etc.

**C. Match question vs available data:**
   - If user asks for info that EXISTS in history → Can answer from history
   - If user asks for info that DOES NOT exist in history → Need database/LLM

## STEP 2: CLASSIFY (Based on your understanding)

### INVALID - Not a chat query (needs routing)

If the user is:
- Stating a NEED/REQUIREMENT with specific specs: "I need a pressure transmitter", "I want 3 transmitters for X service"
  → Route to Solution page
- Requesting SELECTION or RECOMMENDATION with specs: "select the best instruments", "recommend a transmitter for oil and gas", "pick the best option for my application"
  → Route to Solution page (even if they mention vendors or specs)
- Requesting a FULL SOLUTION/BOM: "find instruments for my plant", "create a list of sensors for my pipeline"
  → Route to Solution page
- Completely unrelated: weather, jokes, politics, recipes
  → Out of scope

**KEY DISTINCTION**: "tell me about vendors" = VALID chat. "I need 3 transmitters, select the best for me" = INVALID (Solution page).

### VALID_FOLLOWUP - Can answer from history

The question can be answered using ONLY what's in the conversation history:

**When to use FOLLOWUP:**
- Asking about vendors/products ALREADY mentioned AND the requested information IS in history
- References like "the first one", "that vendor", "it", "both"
- Asking for clarification about something already discussed

**Examples:**
✅ History: "Vendors: ABB, Emerson" + Query: "tell me about ABB" → FOLLOWUP (can give general info using name)
✅ History: "ABB models: 2600T, 2700T" + Query: "what models does ABB have?" → FOLLOWUP (models in history)
✅ History: "ABB: HART protocol. Emerson: SIL rated" + Query: "compare them" → FOLLOWUP (comparison data in history)
✅ History: "Vendors: ABB, Emerson" + Query: "which vendors are common?" → FOLLOWUP (can identify from names in history)
✅ History: "ABB has 500ms response time, Emerson has 250ms." + Query: "which is fastest?" → FOLLOWUP (data is in history)
✅ History: "Emerson is used offshore." + Query: "which would you recommend for offshore?" → FOLLOWUP (data is in history)

### VALID_NEW_QUERY - Need database OR LLM knowledge

The question CANNOT be answered from history alone:

**When to use NEW_QUERY:**
- Asking for SPECIFIC INFORMATION that is NOT in the conversation history
- Different product type than discussed
- Educational/conceptual questions ("how does X work?", "what is X?")
- Comparison when history lacks the required details

**Examples:**
❌ History: "Vendors: ABB, Emerson" + Query: "what models does ABB have?" → NEW_QUERY (models NOT in history)
❌ History: "Vendors: ABB, Emerson" + Query: "specifications of Emerson?" → NEW_QUERY (specs NOT in history)
❌ History: "Vendors: ABB, Emerson" + Query: "certifications?" → NEW_QUERY (certifications NOT in history)
❌ History: "Vendors: ABB, Emerson" + Query: "compare them" → NEW_QUERY (no comparison details in history!)
❌ History: "pressure transmitter" + Query: "what about temperature?" → NEW_QUERY (different product type)
❌ Query: "how does a pressure transmitter work?" → NEW_QUERY (educational - needs LLM knowledge)

## CRITICAL RULE

**The ONLY way to decide FOLLOWUP vs NEW_QUERY is to check if the requested information EXISTS in the conversation history.**

DON'T rely on keywords or patterns - THINK about what information is actually available!

## OUTPUT FORMAT
Reply with ONLY one of these three words:
- VALID_FOLLOWUP
- VALID_NEW_QUERY
- INVALID

CLASSIFICATION:"""

        prompt = ChatPromptTemplate.from_template(prompt_template)
        chain = prompt | llm | StrOutputParser()

        # Use full context or truncate if extremely large
        context_to_use = conversation_context if len(conversation_context) < 50000 else conversation_context[-50000:]
        if not has_history:
            context_to_use = "No previous conversation history."

        logger.info(f"[CHAT_AGENT] Combined classification with {len(context_to_use)} chars of context")

        classification = chain.invoke({
            "conversation_context": context_to_use,
            "query": user_query
        }).strip().upper()

        # Parse the classification result - check exact matches first
        classification_clean = classification.strip().upper()

        logger.info(f"[CHAT_AGENT] LLM classification result: '{classification_clean}'")

        # Check for exact matches first (most reliable)
        if classification_clean == "VALID_FOLLOWUP":
            if not has_history:
                logger.info("[CHAT_AGENT] → VALID_NEW_QUERY (no history, forced)")
                return "VALID_NEW_QUERY"
            logger.info("[CHAT_AGENT] → VALID_FOLLOWUP (answer from history)")
            return "VALID_FOLLOWUP"

        elif classification_clean == "VALID_NEW_QUERY":
            logger.info("[CHAT_AGENT] → VALID_NEW_QUERY (needs database)")
            return "VALID_NEW_QUERY"

        elif classification_clean == "INVALID":
            logger.info("[CHAT_AGENT] → INVALID (needs routing)")
            return "INVALID"

        # Fuzzy matching if exact match fails
        elif "INVALID" in classification_clean:
            logger.info("[CHAT_AGENT] → INVALID (fuzzy match)")
            return "INVALID"

        elif "FOLLOWUP" in classification_clean:
            if not has_history:
                logger.info("[CHAT_AGENT] → VALID_NEW_QUERY (no history, forced)")
                return "VALID_NEW_QUERY"
            logger.info("[CHAT_AGENT] → VALID_FOLLOWUP (fuzzy match)")
            return "VALID_FOLLOWUP"

        elif "NEW" in classification_clean and "QUERY" in classification_clean:
            logger.info("[CHAT_AGENT] → VALID_NEW_QUERY (fuzzy match)")
            return "VALID_NEW_QUERY"

        else:
            # Default to VALID_NEW_QUERY if completely unclear
            logger.warning(f"[CHAT_AGENT] Unclear classification: '{classification_clean}', defaulting to VALID_NEW_QUERY")
            return "VALID_NEW_QUERY"

    except Exception as e:
        logger.error(f"[CHAT_AGENT] Combined classification error: {e}, defaulting to VALID_NEW_QUERY")

        # Send notification for query classification error
        _notify_failure("Chat Query Classification",
            f"Chat query classification failed: {str(e)}",
            query=user_query[:200], error=str(e))

        return "VALID_NEW_QUERY"


def _answer_followup_with_context(user_query: str, session_id: str) -> dict[str, Any]:
    """
    Answer follow-up question using ONLY conversation history (no database queries).
    Much faster than full chat_rag since it skips database loading.

    Args:
        user_query: Follow-up question
        session_id: Session ID for conversation history

    Returns:
        Dict with answer and metadata
    """
    try:
        logger.info("[CHAT_AGENT] Answering follow-up with conversation context only")

        # Get full conversation history
        conversation_context = _get_full_conversation_context(session_id)

        # Initialize LLM (no web search needed for follow-ups)
        llm = get_flash_llm(temperature=0.1)

        # Simple prompt for follow-up questions
        prompt_template = """You are an industrial automation expert. Answer the user's follow-up question based ONLY on the conversation history below.

CONVERSATION HISTORY:
{conversation_context}

USER'S FOLLOW-UP QUESTION:
{query}

INSTRUCTIONS:
- Answer based on the information already discussed in the conversation
- If the user is asking about "the first one", "it", "that vendor", etc., identify what they're referring to from the conversation history
- **Use clean, professional formatting:**
  * For vendor lists: Use **bold** vendor names with bullet points for products/details
  * For comparisons: Use markdown tables
  * For common vendors: List with product details, not just names
- Keep your answer focused and concise
- NO plain text lists - always use proper markdown formatting

ANSWER:"""

        prompt = ChatPromptTemplate.from_template(prompt_template)
        chain = prompt | llm | StrOutputParser()

        answer = chain.invoke({
            "conversation_context": conversation_context,
            "query": user_query
        })

        logger.info(f"[CHAT_AGENT] Generated follow-up answer ({len(answer)} chars) using conversation history only")

        return {
            "answer": answer,
            "source": "conversation_history_only",
            "is_followup": True,
            "has_user_context": False,
            "context_length": len(conversation_context),
            "database_queried": False
        }

    except Exception as e:
        logger.exception(f"[CHAT_AGENT] Error answering follow-up: {e}")

        # Notify admin
        _notify_failure("Chat Follow-up Question",
            f"Error answering follow-up: {str(e)}",
            user_query=user_query[:200])

        return {
            "answer": "I apologize, but I encountered an error processing your follow-up question.",
            "source": "error",
            "error": str(e)
        }


# ============================================================================
# MAIN CHAT REQUEST PROCESSOR (Optimized - Single LLM Classification)
# ============================================================================
