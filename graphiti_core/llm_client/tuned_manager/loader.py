import os
import yaml
import re
from typing import Dict, Any, Optional, List
from pathlib import Path

# Try to import pkg_resources, but don't fail if it's not available
try:
    import pkg_resources
    HAS_PKG_RESOURCES = True
except ImportError:
    HAS_PKG_RESOURCES = False

# Try to import dotenv, but don't fail if it's not available
try:
    from dotenv import load_dotenv
    # Load environment variables from .env file
    load_dotenv()
except ImportError:
    # If dotenv is not available, just continue without loading .env
    pass

# Get configuration root directory from environment variable
CONFIG_ROOT = os.environ.get('LLM_CONFIG_ROOT', 'configs')
CONFIG_PROFILE = os.environ.get('LLM_CONFIG_PROFILE', 'default')

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
    """Get the paths to the configuration files in order of precedence."""
    base_paths = []

    # Add group-specific path if group_id is provided
    if group_id:
        base_paths.append(f"{CONFIG_ROOT}/groups/group_{group_id}")

    # Add profile-specific path if not using default
    if CONFIG_PROFILE != 'default':
        base_paths.append(f"{CONFIG_ROOT}/{CONFIG_PROFILE}")

    # Always add default path
    base_paths.append(f"{CONFIG_ROOT}/default")

    # Build full paths for each base path
    full_paths = []
    for base_path in base_paths:
        # Add default config
        full_paths.append(f"{base_path}/llm/default.yaml")

        # Add client-specific config if provided
        if client_type:
            full_paths.append(f"{base_path}/llm/clients/{client_type.lower()}.yaml")

        # Add model-specific config if provided
        if model_name:
            # Convert model name to a valid file name
            model_file = model_name.lower().replace(":", "_").replace(".", "_").replace("-", "_")
            full_paths.append(f"{base_path}/llm/models/{model_file}.yaml")

    return full_paths

def load_yaml_config(config_path: str) -> Dict[str, Any]:
    """Load a YAML configuration file."""
    try:
        # Try direct file access first
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f) or {}
            return resolve_env_vars(config)  # Resolve environment variables
    except (FileNotFoundError, yaml.YAMLError):
        # Try using Path for better cross-platform compatibility
        try:
            path = Path(config_path)
            if path.exists():
                with path.open('r') as f:
                    config = yaml.safe_load(f) or {}
                    return resolve_env_vars(config)  # Resolve environment variables
        except (FileNotFoundError, yaml.YAMLError):
            pass

        # Try package resources if available
        if HAS_PKG_RESOURCES:
            try:
                package_path = config_path.replace(f"{CONFIG_ROOT}/", "")
                config_data = pkg_resources.resource_string("graphiti_core", package_path)
                config = yaml.safe_load(config_data) or {}
                return resolve_env_vars(config)  # Resolve environment variables
            except (FileNotFoundError, yaml.YAMLError, Exception):
                pass

        # If all methods fail, return empty dict
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
    config = {}

    # For tracking inheritance information
    param_sources = {}
    loaded_files = []

    # Get config paths in order of precedence
    config_paths = get_config_paths(section, client_type, model_name, group_id)

    # Load and merge configs in order (later configs override earlier ones)
    section_found = False
    for path in config_paths:
        yaml_config = load_yaml_config(path)

        # Track loaded files
        if inheritance_info:
            file_exists = os.path.exists(path)
            loaded_files.append({
                "path": path,
                "exists": file_exists,
                "content": yaml_config if file_exists else None
            })

        # Merge common settings if looking for a specific section
        if section != "common" and "common" in yaml_config:
            # Track parameter sources before updating
            if inheritance_info:
                for key, value in yaml_config["common"].items():
                    if key not in config or config[key] != value:
                        param_sources[key] = {
                            "file": path,
                            "section": "common",
                            "value": value
                        }

            config.update(yaml_config["common"])

        # Merge section-specific settings
        if section in yaml_config:
            # Track parameter sources before updating
            if inheritance_info:
                for key, value in yaml_config[section].items():
                    if key not in config or config[key] != value:
                        param_sources[key] = {
                            "file": path,
                            "section": section,
                            "value": value
                        }

            config.update(yaml_config[section])
            section_found = True

    # If the section wasn't found in any config file and it's not a special section,
    # try to load the default configuration
    if not section_found and section not in ["common", "model_selection", "connections", "default"]:
        # Load the default configuration
        if inheritance_info:
            default_result = load_config("default", client_type, model_name, group_id, inheritance_info=True)
            default_config = default_result["config"]

            # Add default sources to our sources
            for key, source in default_result["sources"].items():
                if key not in param_sources:
                    param_sources[key] = source

            # Add default files to our files
            loaded_files.extend(default_result["files"])
        else:
            default_config = load_config("default", client_type, model_name, group_id)

        # Merge with any settings we did find
        default_config.update(config)
        config = default_config

    # Return with or without inheritance information
    if inheritance_info:
        return {
            "config": config,
            "sources": param_sources,
            "files": loaded_files
        }
    else:
        return config

def get_connection_config(client_type: str, instance: Optional[str] = None,
                         group_id: Optional[str] = None) -> Dict[str, Any]:
    """Get connection configuration for a specific client type and instance."""
    # Load the default configuration with potential group override
    default_config = load_yaml_config(get_config_paths("connections", group_id=group_id)[0])

    # Get connection settings
    connections = default_config.get("connections", {})
    client_config = connections.get(client_type, {})

    # For clients with multiple instances (like OllamaClient)
    if "instances" in client_config and instance:
        instances = client_config.get("instances", {})
        instance_config = instances.get(instance, {})
        return instance_config

    # For clients without instances
    return client_config

def get_client_settings(client_type: str, group_id: Optional[str] = None) -> Dict[str, Any]:
    """Get client-specific settings."""
    # Load the default configuration with potential group override
    default_config = load_yaml_config(get_config_paths("connections", group_id=group_id)[0])

    # Get connection settings
    connections = default_config.get("connections", {})
    client_config = connections.get(client_type, {})

    # Return client settings
    return client_config.get("settings", {})


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
