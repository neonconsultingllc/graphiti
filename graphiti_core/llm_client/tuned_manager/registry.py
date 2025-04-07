import importlib
import inspect
import os
import pkgutil
from typing import Dict, Type, Optional

from ..client import LLMClient

class ClientRegistry:
    """Registry for LLM client classes that auto-discovers clients in the llm_client directory."""
    
    _client_classes: Dict[str, Type[LLMClient]] = {}
    _initialized = False
    
    @classmethod
    def initialize(cls):
        """Discover and register all LLM client classes."""
        if cls._initialized:
            return
        
        # Get the directory of the current module
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Get the package name
        package_name = __name__.rsplit('.', 1)[0]
        
        # Discover all modules in the package
        for _, module_name, is_pkg in pkgutil.iter_modules([current_dir]):
            # Skip if it's a package or doesn't end with _client
            if is_pkg or not module_name.endswith('_client'):
                continue
            
            # Import the module
            module = importlib.import_module(f"{package_name}.{module_name}")
            
            # Find all classes in the module that inherit from LLMClient
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if (issubclass(obj, LLMClient) and 
                    obj is not LLMClient and 
                    obj.__module__ == module.__name__):
                    # Register the client class
                    cls._client_classes[name] = obj
        
        cls._initialized = True
    
    @classmethod
    def get_client_class(cls, client_type: str) -> Optional[Type[LLMClient]]:
        """Get a client class by name."""
        if not cls._initialized:
            cls.initialize()
        
        return cls._client_classes.get(client_type)
    
    @classmethod
    def get_all_client_classes(cls) -> Dict[str, Type[LLMClient]]:
        """Get all registered client classes."""
        if not cls._initialized:
            cls.initialize()
        
        return cls._client_classes.copy()

def register_client(cls):
    """Decorator to register a client class."""
    ClientRegistry._client_classes[cls.__name__] = cls
    return cls
