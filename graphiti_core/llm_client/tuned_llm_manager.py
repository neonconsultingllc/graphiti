from typing import Dict, Optional, Any, Type
import logging
import time
import os
import httpx
from pydantic import BaseModel

# Configure logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Method to enable debug logging
def enable_debug_logging():
    """Enable debug logging for the TunedLLMManager and related modules."""
    logger.setLevel(logging.DEBUG)
    logging.getLogger('graphiti_core.llm_client.tuned_manager').setLevel(logging.DEBUG)
    logging.getLogger('graphiti_core.llm_client.tuned_manager.context').setLevel(logging.DEBUG)

from .client import LLMClient, DEFAULT_MAX_TOKENS
from .config import LLMConfig
from ..prompts.models import Message
# Import the prompt library
from ..prompts import prompt_library
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
        """Initialize with an optional configuration and group ID.

        Args:
            config: Optional LLM configuration
            cache: Whether to enable response caching in the base LLMClient
            group_id: Optional group ID for group-specific configurations
        """
        # Pass the cache parameter to the base class
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
        # This will not use caching unless explicitly enabled via environment variable
        self.model_selection = self.get_config("model_selection", group_id=self.group_id)

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
        # Get parameters from kwargs
        client_type = kwargs.pop("client_type", None)
        instance = kwargs.pop("instance", None)
        model_name = kwargs.pop("model_name", None)
        group_id = kwargs.pop("group_id", None)

        # Determine the prompt type from the system message
        prompt_type = self._determine_prompt_type_from_library(messages)

        logger.debug("Using prompt_type: %s", prompt_type)

        # Use provided group_id or fall back to self.group_id
        effective_group_id = group_id if group_id is not None else self.group_id
        logger.debug("Using effective_group_id: %s", effective_group_id)

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

        # Get configuration using our centralized method
        config = self.get_config(prompt_type, client_type, model_name, effective_group_id)

        # Apply content-based adjustments if needed based on message length
        if messages and "max_tokens" in config:
            # Calculate total content length
            content_length = sum(len(msg.content) for msg in messages if msg.content)
            if content_length > 10000:
                # For long content, increase max_tokens
                config["max_tokens"] = min(32768, config["max_tokens"] * 2)

        # Merge with any explicitly provided kwargs (these take highest precedence)
        merged_config = {**config, **kwargs}

        # Use max_tokens from config unless explicitly overridden in the method call
        config_max_tokens = config.get("max_tokens")
        if config_max_tokens is not None:
            # Only use the config value if max_tokens wasn't explicitly provided
            if max_tokens == DEFAULT_MAX_TOKENS:
                logger.debug("Using max_tokens=%s from config", config_max_tokens)
                max_tokens = config_max_tokens
            else:
                # max_tokens was explicitly provided, override the config value
                logger.debug("Overriding config max_tokens=%s with provided value %s", config_max_tokens, max_tokens)
                config["max_tokens"] = max_tokens

        # Call the client with the tuned configuration
        if client is self:
            # Avoid infinite recursion
            raise ValueError("No suitable client found and no default client provided")

        # Handle client-specific parameter mapping
        client_type = client.__class__.__name__
        logger.debug("Client type: %s", client_type)

        if client_type == "OllamaClient":
            # OllamaClient handles temperature and other parameters internally
            # It only accepts messages, response_model, and max_tokens as parameters

            # Set client properties for parameters that it handles internally
            if "temperature" in merged_config:
                client.temperature = merged_config["temperature"]
                logger.debug("Setting OllamaClient.temperature to %s", client.temperature)

            # Extract max_tokens from merged_config if present
            max_tokens_value = merged_config.get("max_tokens", max_tokens)
            logger.debug("Using max_tokens=%s for OllamaClient", max_tokens_value)

            # Call with only the parameters it accepts
            logger.debug("Calling OllamaClient._generate_response with max_tokens=%s", max_tokens_value)
            return await client._generate_response(messages, response_model, max_tokens_value)
        else:
            # For other clients, filter out parameters that the client doesn't accept
            import inspect
            client_params = inspect.signature(client._generate_response).parameters
            filtered_config = {k: v for k, v in merged_config.items()
                              if k in client_params}

            logger.debug("Filtered config parameters: %s -> %s",
                       list(merged_config.keys()), list(filtered_config.keys()))

            return await client._generate_response(messages, response_model, **filtered_config)

    async def get_client(self, prompt_type: str, client_type: Optional[str] = None,
                        instance: Optional[str] = None, model_name: Optional[str] = None,
                        group_id: Optional[str] = None) -> LLMClient:
        """Get or create a client for the specified prompt type, client type, instance, and model."""
        logger.debug("get_client called with prompt_type=%s, client_type=%s, instance=%s, model_name=%s, group_id=%s",
                   prompt_type, client_type, instance, model_name, group_id)
        # Use provided group_id or fall back to self.group_id
        effective_group_id = group_id if group_id is not None else self.group_id

        # Get model selection using our centralized method
        model_selection = self.get_config("model_selection", group_id=effective_group_id)
        logger.debug("Using model_selection: %s", model_selection)

        logger.debug("Model selection: %s", model_selection)

        # Determine which client, instance, and model to use
        client_config = None
        if prompt_type in model_selection and isinstance(model_selection[prompt_type], dict):
            client_config = model_selection.get(prompt_type, {})
            logger.debug("Found client_config for prompt_type %s: %s", prompt_type, client_config)
        else:
            logger.debug("No client_config found for prompt_type %s", prompt_type)

        # Get default values
        default_client_type = model_selection.get("default_client", "OllamaClient")
        default_instance = model_selection.get("default_instance", "local")
        default_model = model_selection.get("default_model")
        logger.debug("Default values: client_type=%s, instance=%s, model=%s",
                   default_client_type, default_instance, default_model)

        if client_config and "client" in client_config:
            # Use prompt-specific client if specified
            client_type = client_config.get("client")
            instance = client_config.get("instance")
            model_name = client_config.get("model")
            logger.debug("Using prompt-specific client: client_type=%s, instance=%s, model=%s",
                       client_type, instance, model_name)
        else:
            # Fall back to defaults or explicitly provided values
            client_type = client_type or default_client_type
            instance = instance or default_instance
            model_name = model_name or default_model
            logger.debug("Using default client: client_type=%s, instance=%s, model=%s",
                       client_type, instance, model_name)

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
            logger.debug("Using existing client for %s/%s/%s", client_type, instance, model_name)
            return self.clients[client_type][instance][model_name]

        # Try to create the client
        try:
            # Use provided group_id or fall back to self.group_id
            effective_group_id = group_id if group_id is not None else self.group_id
            logger.debug("Creating new client for %s/%s/%s with group_id=%s",
                       client_type, instance, model_name, effective_group_id)

            client = await self._create_client(client_type, instance, model_name, group_id=effective_group_id)
            logger.debug("Client created successfully: %s", client)

            # Store for reuse
            if client_type not in self.clients:
                self.clients[client_type] = {}
            if instance not in self.clients[client_type]:
                self.clients[client_type][instance] = {}
            self.clients[client_type][instance][model_name] = client
            logger.debug("Client stored for reuse")

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
        logger.debug("_create_client called with client_type=%s, instance=%s, model_name=%s, group_id=%s",
                   client_type, instance, model_name, group_id)

        # Use provided group_id or fall back to self.group_id
        effective_group_id = group_id if group_id is not None else self.group_id
        logger.debug("Using effective_group_id: %s", effective_group_id)

        # Get connection configuration for this client type and instance
        connection_config = get_connection_config(client_type, instance, group_id=effective_group_id)
        logger.debug("Connection config: %s", connection_config)

        # Get client settings
        settings = self.client_settings.get(client_type, {})
        logger.debug("Client settings: %s", settings)

        # Create LLM configuration
        config = LLMConfig(
            model=model_name,
            base_url=connection_config.get("base_url"),
            api_key=connection_config.get("api_key"),
            # Add client settings to the config
            **{k: v for k, v in settings.items() if k not in ["health_endpoint"]}
        )
        logger.debug("Created LLMConfig: %s", config)

        # Get the client class from the registry
        client_class = ClientRegistry.get_client_class(client_type)
        logger.debug("Got client class for %s: %s", client_type, client_class)

        if client_class:
            # Create an instance of the client class
            logger.debug("Creating instance of %s", client_class.__name__)
            client = client_class(config=config)
            logger.debug("Created client: %s", client)
            return client
        else:
            logger.error("Unsupported client type: %s", client_type)
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

    def get_config(self, config_type: str, client_type: Optional[str] = None,
                 model_name: Optional[str] = None, group_id: Optional[str] = None) -> Dict[str, Any]:
        """Get configuration with optional in-memory caching.

        This method loads configuration from files with optional in-memory caching.
        Caching is controlled by the GRAPHITI_USE_CONFIG_CACHE environment variable.
        Caching is DISABLED by default - it will only be used if explicitly enabled.

        Args:
            config_type: The type of configuration to load (e.g., "model_selection", "dedupe_nodes.node_list")
            client_type: Optional client type for client-specific configurations
            model_name: Optional model name for model-specific configurations
            group_id: Optional group ID for group-specific configurations

        Returns:
            The loaded configuration
        """
        effective_group_id = group_id if group_id is not None else self.group_id

        # Check if in-memory caching is enabled via environment variable
        use_cache = os.environ.get('GRAPHITI_USE_CONFIG_CACHE', '').lower() in ('true', '1', 'yes')

        # Only use caching if explicitly enabled
        if use_cache:
            # Create a cache key that uniquely identifies this configuration
            cache_key = f"{config_type}:{client_type or ''}:{model_name or ''}:{effective_group_id}"

            # Initialize cache if needed
            if not hasattr(self, '_config_cache'):
                self._config_cache = {}
                logger.debug("Initialized in-memory config cache")

            # If we have a cached value, return it
            if cache_key in self._config_cache:
                logger.debug(f"Using cached config for {config_type}")
                return self._config_cache[cache_key]

        # Load the configuration from files
        try:
            config = load_config(config_type, client_type, model_name, group_id=effective_group_id)
            logger.debug(f"Loaded config for {config_type}: {config}")
        except Exception as e:
            logger.warning(f"Error loading config for {config_type}: {str(e)}")
            # Fall back to default configuration
            config = load_config("default", client_type, model_name, group_id=effective_group_id)
            logger.debug(f"Loaded default config: {config}")

        # Cache the configuration if caching is enabled
        if use_cache:
            self._config_cache[cache_key] = config
            logger.debug(f"Cached config for {config_type}")

        return config

    def _determine_prompt_type_from_library(self, messages: list[Message]) -> str:
        """Determine the prompt type by comparing the system message with the prompt library.

        This method uses the prompt library to determine the prompt type by comparing
        the system message with the templates in the prompt library.

        Args:
            messages: The messages to analyze

        Returns:
            The prompt library path (e.g., 'extract_nodes.extract_text') or 'default'
        """
        if not messages:
            logger.debug("No messages to analyze")
            return "default"

        # Get the system message content if available
        system_content = None
        for msg in messages:
            if msg.role == "system" and msg.content:
                system_content = msg.content
                break

        if not system_content:
            logger.debug("No system message found")
            return "default"

        # Try to match the system message with prompt library templates
        # We'll dynamically discover the structure from the prompt library

        # Dynamically discover the top-level categories in the prompt library
        top_level_categories = [attr for attr in dir(prompt_library)
                              if not attr.startswith('_') and
                              hasattr(getattr(prompt_library, attr), '__call__') == False]

        # Dynamically discover the sub-categories for each top-level category
        sub_categories = {}
        for category in top_level_categories:
            category_module = getattr(prompt_library, category)
            sub_categories[category] = [attr for attr in dir(category_module)
                                      if not attr.startswith('_') and
                                      hasattr(getattr(category_module, attr), '__call__')]

        # Try to match the system message with each prompt template
        for category in top_level_categories:
            for sub_category in sub_categories.get(category, []):
                try:
                    # Get the prompt function
                    category_module = getattr(prompt_library, category)
                    prompt_func = getattr(category_module, sub_category)

                    # Create a minimal context to get the template
                    # Different prompt functions expect different context parameters
                    # We'll try with an empty dict first, and if that fails, we'll try with
                    # some common parameters
                    try:
                        template_messages = prompt_func({})
                    except Exception:
                        # Try with some common parameters
                        try:
                            template_messages = prompt_func({"previous_episodes": []})
                        except Exception:
                            # Try with more parameters
                            try:
                                template_messages = prompt_func({
                                    "previous_episodes": [],
                                    "nodes": [],
                                    "edges": [],
                                    "related_edges": [],
                                    "existing_edges": [],
                                    "node_summaries": [],
                                    "summary": "",
                                    "entity_summaries": [],
                                    "query": ""
                                })
                            except Exception:
                                # Skip this prompt if we can't get the template
                                continue

                    # Check if the first message is a system message
                    if template_messages and template_messages[0].role == 'system':
                        template_content = template_messages[0].content
                        # Check if the system message matches the template exactly
                        if system_content == template_content:
                            logger.debug(f"System message exactly matches {category}.{sub_category}")
                            return f"{category}.{sub_category}"
                        # If not an exact match, check if it starts with the template
                        # This is a fallback for cases where the system message might have additional content
                        elif system_content.startswith(template_content):
                            logger.debug(f"System message starts with {category}.{sub_category} template")
                            return f"{category}.{sub_category}"
                except Exception as e:
                    logger.debug(f"Error checking {category}.{sub_category}: {str(e)}")

        # Default to "default" if no match is found
        logger.debug("No match found in prompt library for system message")
        return "default"

