from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Dict, Any

class PromptType(Enum):
    NODE_EXTRACTION = auto()
    EDGE_EXTRACTION = auto()
    NODE_REFLEXION = auto()
    EDGE_REFLEXION = auto()
    SUMMARIZATION = auto()
    CLASSIFICATION = auto()
    # Add other prompt types as needed

@dataclass
class LLMRequestContext:
    """Context information about an LLM request."""
    # Source information
    prompt_type: Optional[PromptType] = None
    source_module: Optional[str] = None
    source_function: Optional[str] = None
    
    # Content information
    content_length: Optional[int] = None
    content_type: Optional[str] = None
    
    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_caller(cls, prompt_type: PromptType = None, **kwargs) -> "LLMRequestContext":
        """Create context from the calling function."""
        import inspect
        frame = inspect.currentframe().f_back.f_back  # Go back two frames to get the caller
        module = inspect.getmodule(frame)
        function_name = frame.f_code.co_name
        
        return cls(
            prompt_type=prompt_type,
            source_module=module.__name__ if module else None,
            source_function=function_name,
            **kwargs
        )
