"""
TunedLLMManager - A context-aware, multi-model LLM client manager.

This package provides a manager for LLM clients that handles:
- Context-aware parameter tuning
- Multi-client support
- Multi-model selection
- Group-specific configurations
"""

from .manager import TunedLLMManager

__all__ = ["TunedLLMManager"]
