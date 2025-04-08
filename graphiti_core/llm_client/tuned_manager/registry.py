import importlib
import logging
from typing import Dict, Type, Optional

from ..client import LLMClient

# Configure logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class ClientRegistry:
    """Registry for LLM client classes."""

    _client_classes: Dict[str, Type[LLMClient]] = {}
    _initialized = False

    @classmethod
    def initialize(cls):
        """Initialize the registry (no-op as clients are loaded on demand)."""
        cls._initialized = True
        logger.debug("ClientRegistry initialized")

    @classmethod
    def get_client_class(cls, client_type: str) -> Optional[Type[LLMClient]]:
        """Get a client class by name, importing it if necessary."""
        logger.debug("get_client_class called with client_type=%s", client_type)

        # If already registered, return it
        if client_type in cls._client_classes:
            logger.debug("Found client class in registry: %s", client_type)
            return cls._client_classes[client_type]

        # Initialize if not already done
        if not cls._initialized:
            logger.debug("ClientRegistry not initialized, initializing now")
            cls.initialize()

        # Try to import the client class directly
        try:
            logger.debug("Importing client class: graphiti_core.llm_client.%s", client_type)
            module = importlib.import_module("graphiti_core.llm_client")
            client_class = getattr(module, client_type)

            # Verify it's a subclass of LLMClient
            if issubclass(client_class, LLMClient):
                logger.debug("Successfully imported client class: %s", client_type)
                cls._client_classes[client_type] = client_class
                return client_class
            else:
                logger.warning("%s is not a subclass of LLMClient", client_type)
                return None
        except (ImportError, AttributeError) as e:
            logger.warning("Failed to import client class %s: %s", client_type, str(e))
            return None

    @classmethod
    def get_all_client_classes(cls) -> Dict[str, Type[LLMClient]]:
        """Get all registered client classes."""
        logger.debug("get_all_client_classes called")

        if not cls._initialized:
            logger.debug("ClientRegistry not initialized, initializing now")
            cls.initialize()

        logger.debug("Returning %d client classes: %s",
                   len(cls._client_classes), list(cls._client_classes.keys()))
        return cls._client_classes.copy()

def register_client(cls):
    """Decorator to register a client class."""
    logger.debug("Manually registering client class: %s", cls.__name__)
    ClientRegistry._client_classes[cls.__name__] = cls
    return cls
