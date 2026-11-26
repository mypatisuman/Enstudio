import logging
import json
from datetime import datetime, UTC
from typing import Dict, Any, Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from common.ai.llm.manager import get_deterministic_flash
from common.ai.prompts.templates import (
    MAIN_POSITIVE_FEEDBACK_PROMPT,
    MAIN_NEGATIVE_FEEDBACK_PROMPT,
    MAIN_COMMENT_ONLY_FEEDBACK_PROMPT,
    SENTIMENT_ANALYSIS_PROMPT
)
from common.infra.repositories.project_repository import mongo_project_manager

def _analyze_sentiment(comment: str, explicit_rating: str) -> dict[str, Any] | None:
    """Natively analyzes sentiment of the comment using LangChain."""
    if not comment or not comment.strip():
        return {
            "detected_sentiment": explicit_rating if explicit_rating != 'none' else 'neutral',
            "sentiment_score": 1.0 if explicit_rating == 'positive' else (-1.0 if explicit_rating == 'negative' else 0.0),
            "confidence": 0.0,
            "emotions": [],
            "intensity": "low",
            "key_phrases": [],
            "discrepancy": False,
            "explanation": "No comment text to analyze"
        }
    
    try:
        llm = get_deterministic_flash()
        prompt = ChatPromptTemplate.from_template(SENTIMENT_ANALYSIS_PROMPT)
        chain = prompt | llm | StrOutputParser()
        
        response = chain.invoke({
            "comment": comment,
            "explicit_rating": explicit_rating
        })
        
        response_clean = response.strip()
        if response_clean.startswith("```json"): response_clean = response_clean[7:]
        if response_clean.startswith("```"): response_clean = response_clean[3:]
        if response_clean.endswith("```"): response_clean = response_clean[:-3]
        response_clean = response_clean.strip()

        sentiment_data = json.loads(response_clean)
        logging.info(
            f"[SENTIMENT] Analysis complete - Sentiment: {sentiment_data.get('detected_sentiment')}, "
            f"Score: {sentiment_data.get('sentiment_score')}, "
            f"Discrepancy: {sentiment_data.get('discrepancy')}"
        )
        return sentiment_data
        
    except Exception as e:
        logging.error(f"[SENTIMENT] Failed to process sentiment analysis: {e}")
        return None

def process_and_store_feedback(
    user_id: str,
    username: str,
    feedback_type: str,
    comment: str,
    item_metadata: dict,
    project_id: str,
    log_user_query: str
) -> dict:
    """
    Handles unstructured feedback storing and derives an LLM-based response.
    """
    
    # 1. Native Sentiment Analysis
    sentiment_analysis_result = None
    if comment and comment.strip():
        explicit_rating = feedback_type if feedback_type else 'none'
        sentiment_analysis_result = _analyze_sentiment(comment, explicit_rating)

    # 2. Bundle the feedback document context
    feedback_document = {
        'user_id': user_id,
        'user_name': username,
        'timestamp': datetime.now(UTC),
        'feedback_type': feedback_type,
        'comment': comment,
        'item_type': item_metadata.get('itemType'),
        'item_name': item_metadata.get('itemName'),
        'vendor_name': item_metadata.get('vendorName'),
        'category': item_metadata.get('category'),
        'subcategory': item_metadata.get('subcategory'),
        'model_family': item_metadata.get('modelFamily'),
        'sub_model': item_metadata.get('subModel'),
        'model': item_metadata.get('model'),
        'user_query': item_metadata.get('userQuery') or log_user_query,
        'recommendation_context': item_metadata.get('recommendationContext', {}),
        'project_id': project_id,
        'session_id': item_metadata.get('sessionId'),
        'source': item_metadata.get('source', 'unknown'),
        'sentiment_analysis': sentiment_analysis_result if sentiment_analysis_result else None
    }

    # 3. Save purely to mongo feedback pipeline safely
    try:
        result = mongo_project_manager.file_manager.db['feedback'].insert_one(feedback_document)
        logging.info(
            f"[FEEDBACK] ✓ Stored feedback for {item_metadata.get('itemType', 'item')}: "
            f"{item_metadata.get('itemName', 'N/A')} (type: {feedback_type}, "
            f"user: {username}, id: {result.inserted_id})"
        )
    except Exception as e:
        logging.exception(f"[FEEDBACK] Failed to persist feedback to MongoDB: {e}")

    # 4. Generate AI acknowledgment response
    if not feedback_type and not comment:
        return {"error": "No feedback provided."}

    if feedback_type == 'positive':
        prompt_template = MAIN_POSITIVE_FEEDBACK_PROMPT
    elif feedback_type == 'negative':
        prompt_template = MAIN_NEGATIVE_FEEDBACK_PROMPT
    else:
        prompt_template = MAIN_COMMENT_ONLY_FEEDBACK_PROMPT
        
    try:
        llm = get_deterministic_flash()
        prompt = ChatPromptTemplate.from_template(prompt_template)
        feedback_chain = prompt | llm | StrOutputParser()
        llm_response = feedback_chain.invoke({"comment": comment})
        return {"response": llm_response}
    except Exception as e:
        logging.error(f"[FEEDBACK] LLM parsing failed: {e}")
        return {"error": "LLM component is not ready."}
