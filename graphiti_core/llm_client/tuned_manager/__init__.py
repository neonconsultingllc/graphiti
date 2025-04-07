"""
TunedLLMManager - A context-aware, multi-model LLM client manager.

This package provides a manager for LLM clients that handles:
- Context-aware parameter tuning
- Multi-client support
- Multi-model selection
- Group-specific configurations
"""

from .manager import TunedLLMManager
from .context import LLMRequestContext, PromptType

__all__ = ["TunedLLMManager", "LLMRequestContext", "PromptType"]
