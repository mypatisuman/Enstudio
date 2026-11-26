import os
import logging
from functools import cache

logger = logging.getLogger(__name__)

@cache
def load_prompt_file(prompt_filename: str, current_file_path: str = None) -> str:
    """
    Load a prompt markdown file, with caching.
    Uses current_file_path to resolve ../prompts/{prompt_filename} if provided.
    """
    try:
        if current_file_path:
            current_dir = os.path.dirname(current_file_path)
            prompt_path = os.path.join(current_dir, '..', 'prompts', prompt_filename)
        else:
            prompt_path = prompt_filename

        with open(prompt_path, encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Failed to load prompt from {prompt_filename}: {e}")
        return ""

import re

def _safe_secure_filename(filename: str) -> str:
    """Make filename safe for saving."""
    if not filename:
        return "unnamed_file"
    safe_name = re.sub(r'[^a-zA-Z0-9.-]', '_', filename)
    return safe_name.strip('_')

def is_allowed_file(filename: str, allowed_extensions: set = None) -> bool:
    """Check if file has an allowed extension."""
    if not allowed_extensions:
        allowed_extensions = {'pdf', 'txt', 'csv', 'xlsx', 'docx'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

