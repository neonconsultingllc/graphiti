import os
import yaml
import re
from typing import Dict, Any, Optional, List
import pkg_resources
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

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
        try:
            # Fall back to package resources
            package_path = config_path.replace(f"{CONFIG_ROOT}/", "")
            config_data = pkg_resources.resource_string("graphiti_core", package_path)
            config = yaml.safe_load(config_data) or {}
            return resolve_env_vars(config)  # Resolve environment variables
        except (FileNotFoundError, yaml.YAMLError, pkg_resources.DistributionNotFound):
            # If file doesn't exist or has errors, return empty dict
            return {}

def load_config(section: str, client_type: Optional[str] = None, model_name: Optional[str] = None, 
               group_id: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration for the specified section, client, model, and group."""
    config = {}
    
    # Get config paths in order of precedence
    config_paths = get_config_paths(section, client_type, model_name, group_id)
    
    # Load and merge configs in order (later configs override earlier ones)
    for path in config_paths:
        yaml_config = load_yaml_config(path)
        
        # Merge common settings if looking for a specific section
        if section != "common" and "common" in yaml_config:
            config.update(yaml_config["common"])
        
        # Merge section-specific settings
        if section in yaml_config:
            config.update(yaml_config[section])
    
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
