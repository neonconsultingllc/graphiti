from typing import Dict, Optional, Any, Type
import logging
import time
import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from .client import LLMClient, DEFAULT_MAX_TOKENS
from .config import LLMConfig
from ..prompts.models import Message
from .tuned_manager.context import LLMRequestContext
from .tuned_manager.registry import ClientRegistry
from .tuned_manager.loader import (
    load_config, load_yaml_config, get_config_paths,
    get_connection_config, get_client_settings
)

class TunedLLMManager(LLMClient):
    """
    Unified manager for LLM clients that handles:
    - Multiple client types (Ollama, OpenAI, etc.)
    - Multiple instances per client type
    - Multiple models per instance
    - Context-aware parameter tuning
    - Health checking and fallbacks
    - Configuration loading
    - Group-specific configurations
    """

    def __init__(self, config: LLMConfig | None = None, cache: bool = False, group_id: Optional[str] = None):
        """Initialize with an optional configuration and group ID."""
        super().__init__(config, cache)
        self.group_id = group_id
        self.default_client = None  # Will be set to self if no other client is available

        # Initialize the client registry
        ClientRegistry.initialize()

        # Get all available client types
        client_classes = ClientRegistry.get_all_client_classes()

        # Dictionary of client_type -> instance -> model -> client
        self.clients: Dict[str, Dict[str, Dict[str, LLMClient]]] = {
            client_type: {} for client_type in client_classes.keys()
        }

        # Load global model selection config with potential group override
        self.model_selection = load_config("model_selection", group_id=self.group_id)

        # Initialize configuration cache
        self.config_cache: Dict[str, Dict[str, Any]] = {}

        # Cache the model selection configuration
        model_selection_cache_key = f"model_selection:{self.group_id}"
        self.config_cache[model_selection_cache_key] = self.model_selection

        # Health status tracking
        self.health_status: Dict[str, Dict[str, bool]] = {}
        self.last_checked: Dict[str, Dict[str, float]] = {}
        self.check_interval = 60  # Check every 60 seconds

        # Load instance configurations with potential group override
        default_config_path = get_config_paths("connections", group_id=self.group_id)[0]
        default_config = load_yaml_config(default_config_path)
        self.connections = default_config.get("connections", {})

        # Load client settings with potential group override
        self.client_settings = {
            client_type: get_client_settings(client_type, group_id=self.group_id)
            for client_type in client_classes.keys()
        }

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: Type[BaseModel] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate a response using the appropriate client with tuning based on context."""
        # Create a default context if none is provided in kwargs
        context = kwargs.pop("context", None) or LLMRequestContext()

        # Get other parameters from kwargs
        client_type = kwargs.pop("client_type", None)
        instance = kwargs.pop("instance", None)
        model_name = kwargs.pop("model_name", None)
        group_id = kwargs.pop("group_id", None)

        # Get prompt type name
        prompt_type = context.prompt_type.name.lower() if context.prompt_type else "default"

        # Use provided group_id or fall back to self.group_id
        effective_group_id = group_id if group_id is not None else self.group_id

        try:
            # Get the appropriate client for this prompt type
            client = await self.get_client(prompt_type, client_type, instance, model_name, group_id=effective_group_id)

            # Get client details for configuration
            client_type = client.__class__.__name__
            model_name = getattr(client, 'model', None)
        except ValueError:
            # If no client is available, use self as a fallback
            if self.default_client is None:
                # If no default client is provided, use self
                self.default_client = self

            # Use the default client
            client = self.default_client
            client_type = client.__class__.__name__
            model_name = getattr(client, 'model', None)

        # Get configuration from cache or load it
        cache_key = f"{prompt_type}:{client_type}:{model_name}:{effective_group_id}"
        if cache_key not in self.config_cache:
            try:
                config = load_config(prompt_type, client_type, model_name, group_id=effective_group_id)
                # Cache the configuration
                self.config_cache[cache_key] = config
            except Exception as e:
                logger.warning(f"Error loading config for prompt type {prompt_type}: {str(e)}")
                # Fall back to default configuration
                config = load_config("default", client_type, model_name, group_id=effective_group_id)
                # Cache the configuration
                self.config_cache[cache_key] = config
        else:
            # Use cached configuration
            config = self.config_cache[cache_key]

        # Apply content-based adjustments if needed
        if hasattr(context, 'content_length') and context.content_length and context.content_length > 10000 and "max_tokens" in config:
            # For long content, increase max_tokens
            config["max_tokens"] = min(32768, config["max_tokens"] * 2)

        # Override max_tokens from parameter if provided
        if max_tokens != DEFAULT_MAX_TOKENS:
            config["max_tokens"] = max_tokens

        # Merge with any explicitly provided kwargs (these take highest precedence)
        merged_config = {**config, **kwargs}

        # Call the client with the tuned configuration
        if client is self:
            # Avoid infinite recursion
            raise ValueError("No suitable client found and no default client provided")

        return await client._generate_response(messages, response_model, **merged_config)

    async def get_client(self, prompt_type: str, client_type: Optional[str] = None,
                        instance: Optional[str] = None, model_name: Optional[str] = None,
                        group_id: Optional[str] = None) -> LLMClient:
        """Get or create a client for the specified prompt type, client type, instance, and model."""
        # Use provided group_id or fall back to self.group_id
        effective_group_id = group_id if group_id is not None else self.group_id

        # Get model selection from cache or load it
        model_selection_cache_key = f"model_selection:{effective_group_id}"
        if model_selection_cache_key not in self.config_cache:
            # Load model selection configuration
            model_selection = load_config("model_selection", group_id=effective_group_id)
            # Cache it
            self.config_cache[model_selection_cache_key] = model_selection
        else:
            # Use cached model selection
            model_selection = self.config_cache[model_selection_cache_key]

        # Determine which client, instance, and model to use
        client_config = None
        if prompt_type in model_selection and isinstance(model_selection[prompt_type], dict):
            client_config = model_selection.get(prompt_type, {})

        # Get default values
        default_client_type = model_selection.get("default_client", "OllamaClient")
        default_instance = model_selection.get("default_instance", "local")
        default_model = model_selection.get("default_model")

        if client_config and "client" in client_config:
            # Use prompt-specific client if specified
            client_type = client_config.get("client")
            instance = client_config.get("instance")
            model_name = client_config.get("model")
        else:
            # Fall back to defaults or explicitly provided values
            client_type = client_type or default_client_type
            instance = instance or default_instance
            model_name = model_name or default_model

        # Check instance health and potentially use a different instance if this client type supports instances
        if instance and "instances" in self.connections.get(client_type, {}):
            # Check if the specified instance is healthy
            is_healthy = await self.check_health(client_type, instance)

            if not is_healthy:
                # Try to find a healthy instance
                healthy_instance = await self.get_healthy_instance(client_type)

                if healthy_instance:
                    # Log the instance switch
                    logging.warning(
                        f"Ollama instance '{instance}' is unhealthy. "
                        f"Switching to healthy instance '{healthy_instance}'."
                    )

                    instance = healthy_instance
                elif client_config and "fallback" in client_config:
                    # Use fallback configuration
                    fallback = client_config["fallback"]
                    fallback_client_type = fallback.get("client")
                    fallback_instance = fallback.get("instance")
                    fallback_model_name = fallback.get("model")

                    logging.warning(
                        f"No healthy Ollama instances available. "
                        f"Falling back to {fallback_client_type} (instance: {fallback_instance}) with model {fallback_model_name}."
                    )

                    return await self.get_client(
                        prompt_type,
                        fallback_client_type,
                        fallback_instance,
                        fallback_model_name,
                        group_id=group_id
                    )

        # Check if we already have this client/instance/model combination
        if (client_type in self.clients and
            instance in self.clients[client_type] and
            model_name in self.clients[client_type][instance]):
            return self.clients[client_type][instance][model_name]

        # Try to create the client
        try:
            # Use provided group_id or fall back to self.group_id
            effective_group_id = group_id if group_id is not None else self.group_id

            client = await self._create_client(client_type, instance, model_name, group_id=effective_group_id)

            # Store for reuse
            if client_type not in self.clients:
                self.clients[client_type] = {}
            if instance not in self.clients[client_type]:
                self.clients[client_type][instance] = {}
            self.clients[client_type][instance][model_name] = client

            return client
        except Exception as e:
            # If there's a fallback configuration, try that instead
            if client_config and "fallback" in client_config:
                fallback = client_config["fallback"]
                fallback_client_type = fallback.get("client")
                fallback_instance = fallback.get("instance")
                fallback_model_name = fallback.get("model")

                logging.warning(
                    f"Failed to create client {client_type} (instance: {instance}) with model {model_name}: {str(e)}. "
                    f"Falling back to {fallback_client_type} (instance: {fallback_instance}) with model {fallback_model_name}."
                )

                # Try the fallback
                return await self.get_client(
                    prompt_type,
                    fallback_client_type,
                    fallback_instance,
                    fallback_model_name,
                    group_id=group_id
                )
            else:
                # No fallback, re-raise the exception
                raise

    async def _create_client(self, client_type: str, instance: Optional[str] = None,
                           model_name: Optional[str] = None, group_id: Optional[str] = None) -> LLMClient:
        """Create a new client of the specified type, instance, and model."""
        # Use provided group_id or fall back to self.group_id
        effective_group_id = group_id if group_id is not None else self.group_id

        # Get connection configuration for this client type and instance
        connection_config = get_connection_config(client_type, instance, group_id=effective_group_id)

        # Get client settings
        settings = self.client_settings.get(client_type, {})

        # Create LLM configuration
        config = LLMConfig(
            model=model_name,
            base_url=connection_config.get("base_url"),
            api_key=connection_config.get("api_key"),
            # Add client settings to the config
            **{k: v for k, v in settings.items() if k not in ["health_endpoint"]}
        )

        # Get the client class from the registry
        client_class = ClientRegistry.get_client_class(client_type)

        if client_class:
            # Create an instance of the client class
            return client_class(config=config)
        else:
            raise ValueError(f"Unsupported client type: {client_type}")

    async def check_health(self, client_type: str, instance: str) -> bool:
        """Check the health of a client instance."""
        # If we've checked recently, return the cached result
        if (client_type in self.last_checked and
            instance in self.last_checked[client_type] and
            time.time() - self.last_checked[client_type][instance] < self.check_interval):
            return self.health_status.get(client_type, {}).get(instance, False)

        # Initialize dictionaries if needed
        if client_type not in self.health_status:
            self.health_status[client_type] = {}
        if client_type not in self.last_checked:
            self.last_checked[client_type] = {}

        # Get instance details
        client_config = self.connections.get(client_type, {})
        instances = client_config.get("instances", {})
        instance_config = instances.get(instance, {})
        base_url = instance_config.get("base_url")

        if not base_url:
            return False

        # Get client settings
        settings = self.client_settings.get(client_type, {})
        health_endpoint = settings.get("health_endpoint")
        timeout = settings.get("timeout", 5.0)

        # Check health based on client settings
        is_healthy = False
        try:
            if health_endpoint:
                # Determine the full health check URL
                health_url = health_endpoint

                # If the health endpoint doesn't start with http, assume it's a path to append to the base URL
                if not health_endpoint.startswith(('http://', 'https://')):
                    health_url = f"{base_url}{health_endpoint}"

                # Perform health check
                async with httpx.AsyncClient() as client:
                    response = await client.get(health_url, timeout=timeout)

                    # Check if the response indicates the service is healthy
                    # Different services might have different ways to indicate health
                    if response.status_code == 200:
                        is_healthy = True
                    else:
                        # Log the unexpected status code
                        logger.warning(f"Health check for {client_type} instance {instance} returned status code {response.status_code}")
            else:
                # No health endpoint defined, assume healthy
                is_healthy = True
        except Exception as e:
            logger.warning(f"Health check failed for {client_type} instance {instance}: {str(e)}")
            is_healthy = False

        # Update status
        self.health_status[client_type][instance] = is_healthy
        self.last_checked[client_type][instance] = time.time()

        return is_healthy

    async def get_healthy_instance(self, client_type: str) -> Optional[str]:
        """Get a healthy instance for the specified client type."""
        client_config = self.connections.get(client_type, {})
        instances = client_config.get("instances", {})

        # Find any healthy instance
        for instance_name in instances:
            if await self.check_health(client_type, instance_name):
                return instance_name

        return None
