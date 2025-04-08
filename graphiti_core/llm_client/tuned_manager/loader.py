import os
import yaml
import re
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path

# Configure logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Try to import pkg_resources, but don't fail if it's not available
try:
    import pkg_resources
    HAS_PKG_RESOURCES = True
except ImportError:
    HAS_PKG_RESOURCES = False

# Try to import dotenv, but don't fail if it's not available
try:
    from dotenv import load_dotenv
    # Define a function to ensure .env is loaded before accessing environment variables
    def ensure_dotenv_loaded():
        # This will load the .env file if it hasn't been loaded yet
        # or reload it if it has changed
        load_dotenv(override=True)
except ImportError:
    # If dotenv is not available, just continue without loading .env
    def ensure_dotenv_loaded():
        # No-op if dotenv is not available
        pass

# Load .env file at module import time
ensure_dotenv_loaded()

# Default configuration paths
DEFAULT_CONFIG_ROOT = 'configs'
DEFAULT_CONFIG_PROFILE = 'default'

# These will be checked dynamically in get_config_paths to ensure we always use the latest values

def resolve_env_vars(config: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively resolve environment variables in configuration values."""
    resolved_config = {}

    for key, value in config.items():
        if isinstance(value, dict):
            # Recursively resolve nested dictionaries
            resolved_config[key] = resolve_env_vars(value)
        elif isinstance(value, str):
            # Resolve environment variables in strings
            resolved_config[key] = resolve_env_var_in_string(value)
        else:
            # Keep other values as is
            resolved_config[key] = value

    return resolved_config

def resolve_env_var_in_string(value: str) -> str:
    """Resolve environment variables in a string."""
    # Match ${ENV_VAR} pattern
    pattern = r'\${([A-Za-z0-9_]+)}'

    def replace_env_var(match):
        env_var = match.group(1)
        return os.environ.get(env_var, "")

    # Replace all environment variables
    return re.sub(pattern, replace_env_var, value)

def get_config_paths(section: str, client_type: Optional[str] = None, model_name: Optional[str] = None,
                    group_id: Optional[str] = None) -> List[str]:
    """Get the paths to the configuration files in order of precedence.

    Args:
        section: The configuration section to load (e.g., "extract_nodes.extract_text")
        client_type: The client type (e.g., "OllamaClient")
        model_name: The model name (e.g., "llama3.3:70b-instruct-q8_0")
        group_id: The group ID for group-specific configurations

    Returns:
        A list of configuration file paths in order of precedence (highest to lowest)
    """
    logger.debug("get_config_paths called with section=%s, client_type=%s, model_name=%s, group_id=%s",
               section, client_type, model_name, group_id)

    # Ensure .env file is loaded before checking environment variables
    ensure_dotenv_loaded()

    # Get configuration root directory from environment variable - check each time to ensure we use the latest value
    config_root = os.environ.get('LLM_CONFIG_ROOT', DEFAULT_CONFIG_ROOT)
    config_profile = os.environ.get('LLM_CONFIG_PROFILE', DEFAULT_CONFIG_PROFILE)

    logger.debug("Using config_root=%s, config_profile=%s", config_root, config_profile)

    base_paths = []

    # Add group-specific path if group_id is provided
    if group_id:
        group_path = f"{config_root}/groups/group_{group_id}"
        base_paths.append(group_path)
        logger.debug("Added group-specific path: %s", group_path)

    # Add profile-specific path if not using default
    if config_profile != 'default':
        profile_path = f"{config_root}/{config_profile}"
        base_paths.append(profile_path)
        logger.debug("Added profile-specific path: %s", profile_path)

    # Always add default path
    default_path = f"{config_root}/default"
    base_paths.append(default_path)
    logger.debug("Added default path: %s", default_path)

    # Build full paths for each base path
    full_paths = []
    for base_path in base_paths:
        # Add default config
        default_config = f"{base_path}/llm/default.yaml"
        full_paths.append(default_config)
        logger.debug("Added default config path: %s", default_config)

        # Add client-specific config if provided
        if client_type:
            client_config = f"{base_path}/llm/clients/{client_type.lower()}.yaml"
            full_paths.append(client_config)
            logger.debug("Added client-specific config path: %s", client_config)

        # Add model-specific config if provided
        if model_name:
            # Convert model name to a valid file name
            model_file = model_name.lower().replace(":", "_").replace(".", "_").replace("-", "_")
            model_config = f"{base_path}/llm/models/{model_file}.yaml"
            full_paths.append(model_config)
            logger.debug("Added model-specific config path: %s", model_config)

        # Handle prompt library paths
        if section not in ["default", "common", "model_selection", "connections"]:
            # Check if it's a hierarchical path (e.g., "extract_nodes.extract_text")
            if "." in section:
                # Split into parent and child
                parent, child = section.split(".", 1)

                # Add parent config first (e.g., "extract_nodes")
                parent_config = f"{base_path}/llm/prompt_library/{parent}.yaml"
                full_paths.append(parent_config)
                logger.debug("Added parent prompt library config path: %s", parent_config)

                # Add specific child config (e.g., "extract_nodes.extract_text")
                child_config = f"{base_path}/llm/prompt_library/{parent}/{child}.yaml"
                full_paths.append(child_config)
                logger.debug("Added child prompt library config path: %s", child_config)
            else:
                # Just a top-level prompt type
                prompt_type_config = f"{base_path}/llm/prompt_library/{section}.yaml"
                full_paths.append(prompt_type_config)
                logger.debug("Added prompt library config path: %s", prompt_type_config)

                # Also check the old location for backward compatibility
                old_prompt_type_config = f"{base_path}/llm/prompt_types/{section}.yaml"
                full_paths.append(old_prompt_type_config)
                logger.debug("Added old prompt type config path: %s", old_prompt_type_config)

    logger.debug("Final config paths: %s", full_paths)
    return full_paths

def load_yaml_config(config_path: str) -> Dict[str, Any]:
    """Load a YAML configuration file."""
    logger.debug("load_yaml_config called with config_path=%s", config_path)

    try:
        # Try direct file access first
        logger.debug("Trying direct file access for %s", config_path)
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f) or {}
            logger.debug("Successfully loaded config from file: %s", config_path)
            resolved_config = resolve_env_vars(config)  # Resolve environment variables
            logger.debug("Resolved environment variables in config")
            return resolved_config
    except FileNotFoundError:
        logger.debug("File not found: %s", config_path)
    except yaml.YAMLError as e:
        logger.warning("YAML error in %s: %s", config_path, str(e))

    # Try using Path for better cross-platform compatibility
    try:
        logger.debug("Trying Path for %s", config_path)
        path = Path(config_path)
        if path.exists():
            logger.debug("Path exists: %s", path)
            with path.open('r') as f:
                config = yaml.safe_load(f) or {}
                logger.debug("Successfully loaded config from Path: %s", path)
                resolved_config = resolve_env_vars(config)  # Resolve environment variables
                logger.debug("Resolved environment variables in config")
                return resolved_config
    except FileNotFoundError:
        logger.debug("Path not found: %s", path)
    except yaml.YAMLError as e:
        logger.warning("YAML error in path %s: %s", path, str(e))

    # Try package resources if available
    if HAS_PKG_RESOURCES:
        try:
            # Ensure .env file is loaded before checking environment variables
            ensure_dotenv_loaded()

            # Get configuration root directory from environment variable
            config_root = os.environ.get('LLM_CONFIG_ROOT', DEFAULT_CONFIG_ROOT)
            package_path = config_path.replace(f"{config_root}/", "")
            logger.debug("Trying pkg_resources for %s", package_path)
            config_data = pkg_resources.resource_string("graphiti_core", package_path)
            config = yaml.safe_load(config_data) or {}
            logger.debug("Successfully loaded config from pkg_resources: %s", package_path)
            resolved_config = resolve_env_vars(config)  # Resolve environment variables
            logger.debug("Resolved environment variables in config")
            return resolved_config
        except FileNotFoundError:
            logger.debug("Resource not found: %s", package_path)
        except yaml.YAMLError as e:
            logger.warning("YAML error in resource %s: %s", package_path, str(e))
        except Exception as e:
            logger.warning("Error loading resource %s: %s", package_path, str(e))

    # If all methods fail, return empty dict
    logger.debug("All attempts to load config failed, returning empty dict")
    return {}

def load_config(section: str, client_type: Optional[str] = None, model_name: Optional[str] = None,
               group_id: Optional[str] = None, inheritance_info: bool = False) -> Dict[str, Any]:
    """Load configuration for the specified section, client, model, and group.

    Args:
        section: The configuration section to load (e.g., "node_extraction", "model_selection")
        client_type: The client type (e.g., "OllamaClient")
        model_name: The model name (e.g., "llama3.3:70b-instruct-q8_0")
        group_id: The group ID for group-specific configurations
        inheritance_info: Whether to include information about which values came from which files

    Returns:
        If inheritance_info=False, returns the merged configuration.
        If inheritance_info=True, returns a dict with keys:
            - "config": The merged configuration
            - "sources": A dict mapping parameter names to source information
            - "files": A list of configuration files that were loaded
    """
    logger.debug("load_config called with section=%s, client_type=%s, model_name=%s, group_id=%s, inheritance_info=%s",
               section, client_type, model_name, group_id, inheritance_info)

    config = {}

    # For tracking inheritance information
    param_sources = {}
    loaded_files = []

    logger.debug("Initializing empty config and tracking structures")

    # Get config paths in order of precedence
    config_paths = get_config_paths(section, client_type, model_name, group_id)
    logger.debug("Got %d config paths", len(config_paths))

    # Load and merge configs in order (later configs override earlier ones)
    section_found = False
    for path in config_paths:
        logger.debug("Processing config path: %s", path)
        yaml_config = load_yaml_config(path)

        # Track loaded files
        if inheritance_info:
            file_exists = os.path.exists(path)
            logger.debug("Tracking file for inheritance info: %s (exists=%s)", path, file_exists)
            loaded_files.append({
                "path": path,
                "exists": file_exists,
                "content": yaml_config if file_exists else None
            })

        # Merge common settings if looking for a specific section
        if section != "common" and "common" in yaml_config:
            logger.debug("Found common section in %s", path)
            # Track parameter sources before updating
            if inheritance_info:
                for key, value in yaml_config["common"].items():
                    if key not in config or config[key] != value:
                        logger.debug("Tracking source for parameter %s from common section in %s", key, path)
                        param_sources[key] = {
                            "file": path,
                            "section": "common",
                            "value": value
                        }

            config.update(yaml_config["common"])
            logger.debug("Updated config with common settings from %s", path)

        # Merge section-specific settings
        if section in yaml_config:
            logger.debug("Found %s section in %s", section, path)
            # Track parameter sources before updating
            if inheritance_info:
                for key, value in yaml_config[section].items():
                    if key not in config or config[key] != value:
                        logger.debug("Tracking source for parameter %s from %s section in %s", key, section, path)
                        param_sources[key] = {
                            "file": path,
                            "section": section,
                            "value": value
                        }

            config.update(yaml_config[section])
            logger.debug("Updated config with %s settings from %s", section, path)
            section_found = True

    # If the section wasn't found in any config file and it's not a special section,
    # try to load the default configuration
    if not section_found and section not in ["common", "model_selection", "connections", "default"]:
        logger.debug("Section %s not found in any config file, falling back to default", section)
        # Load the default configuration
        if inheritance_info:
            logger.debug("Loading default configuration with inheritance info")
            default_result = load_config("default", client_type, model_name, group_id, inheritance_info=True)
            default_config = default_result["config"]
            logger.debug("Loaded default config: %s", default_config)

            # Add default sources to our sources
            for key, source in default_result["sources"].items():
                if key not in param_sources:
                    logger.debug("Adding source for parameter %s from default config", key)
                    param_sources[key] = source

            # Add default files to our files
            logger.debug("Adding %d files from default config", len(default_result["files"]))
            loaded_files.extend(default_result["files"])
        else:
            logger.debug("Loading default configuration without inheritance info")
            default_config = load_config("default", client_type, model_name, group_id)
            logger.debug("Loaded default config: %s", default_config)

        # Merge with any settings we did find
        default_config.update(config)
        logger.debug("Merged default config with existing settings")
        config = default_config

    # Return with or without inheritance information
    if inheritance_info:
        logger.debug("Returning config with inheritance info: %d parameters, %d sources, %d files",
                   len(config), len(param_sources), len(loaded_files))
        return {
            "config": config,
            "sources": param_sources,
            "files": loaded_files
        }
    else:
        logger.debug("Returning config without inheritance info: %d parameters", len(config))
        return config

def get_connection_config(client_type: str, instance: Optional[str] = None,
                         group_id: Optional[str] = None) -> Dict[str, Any]:
    """Get connection configuration for a specific client type and instance."""
    logger.debug("get_connection_config called with client_type=%s, instance=%s, group_id=%s",
               client_type, instance, group_id)

    # Load the default configuration with potential group override
    config_path = get_config_paths("connections", group_id=group_id)[0]
    logger.debug("Loading connections config from %s", config_path)
    default_config = load_yaml_config(config_path)

    # Get connection settings
    connections = default_config.get("connections", {})
    logger.debug("Found %d connection types in config", len(connections))

    client_config = connections.get(client_type, {})
    logger.debug("Found client config for %s: %s", client_type, client_config)

    # For clients with multiple instances (like OllamaClient)
    if "instances" in client_config and instance:
        logger.debug("Looking for instance-specific settings for %s", instance)
        instances = client_config.get("instances", {})
        instance_config = instances.get(instance, {})
        logger.debug("Found instance config for %s: %s", instance, instance_config)
        return instance_config

    # For clients without instances
    logger.debug("No instance specified or client doesn't support instances, returning client config")
    return client_config

def get_client_settings(client_type: str, group_id: Optional[str] = None) -> Dict[str, Any]:
    """Get client-specific settings."""
    logger.debug("get_client_settings called with client_type=%s, group_id=%s",
               client_type, group_id)

    # Load the default configuration with potential group override
    config_path = get_config_paths("connections", group_id=group_id)[0]
    logger.debug("Loading connections config from %s", config_path)
    default_config = load_yaml_config(config_path)

    # Get connection settings
    connections = default_config.get("connections", {})
    logger.debug("Found %d connection types in config", len(connections))

    client_config = connections.get(client_type, {})
    logger.debug("Found client config for %s: %s", client_type, client_config)

    # Return client settings
    settings = client_config.get("settings", {})
    logger.debug("Returning settings for %s: %s", client_type, settings)
    return settings


def get_prompt_types(group_id: Optional[str] = None) -> List[str]:
    """Get all available prompt types.

    Args:
        group_id: The group ID for group-specific configurations

    Returns:
        A list of prompt type names
    """
    prompt_types = set()

    # Get prompt types from model selection
    model_selection = load_config("model_selection", group_id=group_id)
    for key in model_selection.keys():
        if key not in ["default_client", "default_instance", "default_model"] and isinstance(model_selection[key], dict):
            prompt_types.add(key)

    # Get prompt types from default.yaml
    default_config_path = get_config_paths("default", group_id=group_id)[0]
    if os.path.exists(default_config_path):
        default_config = load_yaml_config(default_config_path)
        for key in default_config.keys():
            if key not in ["common", "model_selection", "connections"] and key not in prompt_types:
                prompt_types.add(key)

    # If no prompt types found, use some common ones
    if not prompt_types:
        prompt_types = {"node_extraction", "edge_extraction", "reflexion", "summarization"}

    return sorted(list(prompt_types))
