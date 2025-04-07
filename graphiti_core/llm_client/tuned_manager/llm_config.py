from typing import Optional, Dict, Any

class LLMConfig:
    """Configuration for an LLM client."""
    
    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        **kwargs
    ):
        """Initialize with model, base URL, API key, and additional parameters."""
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        
        # Store additional parameters
        for key, value in kwargs.items():
            setattr(self, key, value)
