# Multi-Model LLM Architecture Documentation

This documentation provides a comprehensive overview of the Multi-Model LLM Architecture, which enables context-aware tuning, multi-client support, multi-instance support, and multi-model selection for LLM operations in Graphiti.

## Table of Contents

1. [Architecture Overview](01_overview.md)
   - System architecture diagram
   - Key components
   - Request flow
   - Benefits

2. [Configuration System](02_configuration.md)
   - Configuration structure
   - Configuration files
   - Configuration loading
   - Environment variable resolution
   - Configuration sections

3. [Client Registry and Auto-Discovery](03_client_registry.md)
   - Auto-discovery process
   - Client registry design
   - Client implementation requirements
   - Benefits of auto-discovery

4. [TunedLLMManager](04_tuned_llm_manager.md)
   - Class structure
   - Key functionality
   - Integration with Graphiti
   - Usage in extraction functions

5. [Group-Specific Configurations](05_group_specific_configs.md)
   - Configuration hierarchy
   - Directory structure
   - Configuration resolution
   - Using group-specific configurations
   - Benefits of group-specific configurations

## Key Features

- **Context-Aware Tuning**: Automatically adjust parameters based on the prompt type
- **Multi-Client Support**: Seamlessly work with different LLM providers (Ollama, OpenAI, etc.)
- **Multi-Instance Support**: Distribute requests across multiple servers
- **Multi-Model Selection**: Use different models for different tasks
- **Group-Specific Configurations**: Use different configurations for different groups or databases
- **Environment-Specific Profiles**: Switch between configurations for different environments
- **Auto-Discovery**: Automatically discover and register new client implementations
- **Configuration-Driven**: Control behavior through YAML configuration files
- **Health Monitoring**: Automatically detect and avoid unhealthy servers
- **Fallback Mechanisms**: Gracefully handle failures by falling back to alternative clients/models

## Quick Start

To get started with the Multi-Model LLM Architecture:

1. Create the configuration directory structure
2. Create the default configuration file
3. Create group-specific configurations if needed
4. Use the TunedLLMManager as a drop-in replacement for LLMClient
5. Pass group_id when needed to use group-specific configurations
