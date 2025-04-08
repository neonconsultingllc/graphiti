# Using Graphiti with TunedLLMManager

This example demonstrates how to use Graphiti with the TunedLLMManager, which provides advanced features for managing multiple LLM clients and models.

## Overview

The TunedLLMManager is a powerful component that:

1. **Manages multiple LLM clients** (Ollama, OpenAI, etc.)
2. **Selects appropriate models** based on prompt type and configuration
3. **Tunes parameters** based on the context (prompt type, content length, etc.)
4. **Handles health checking and fallbacks** for robust operation
5. **Supports group-specific configurations** for different use cases

## Prerequisites

Before running this example, make sure you have:

1. **Ollama** installed and running locally (typically on http://localhost:11434)
2. **Llama 3.3 models** pulled in Ollama:
   ```bash
   ollama pull llama3.3:latest
   ollama pull llama3.3:70b-instruct-q8_0
   ```
3. **Neo4j** database running locally (typically on bolt://localhost:7687)
4. A database created in Neo4j (e.g., 'local-ai')
5. **Configuration files** set up in `graphiti_core/configs` (see Configuration section below)

## Configuration

The TunedLLMManager uses a hierarchical configuration system with files in the `graphiti_core/configs` directory:

```
graphiti_core/configs/
├── default/
│   └── llm/
│       ├── default.yaml           # Default settings for all prompt types
│       ├── model_selection.yaml   # Model selection configuration
│       ├── clients/
│       │   └── ollamaclient.yaml  # Client-specific settings
│       └── models/
│           └── llama3_3_70b.yaml  # Model-specific settings
└── groups/
    └── test_group/                # Group-specific settings
        └── llm/
            └── default.yaml       # Override defaults for this group
```

### Example Configuration Files

#### `default.yaml`
```yaml
common:
  temperature: 0.7
  top_p: 0.95
  frequency_penalty: 0.0
  presence_penalty: 0.0

node_extraction:
  temperature: 0.2
  max_tokens: 4096

edge_extraction:
  temperature: 0.1
  max_tokens: 8192
```

#### `model_selection.yaml`
```yaml
default_client: OllamaClient
default_instance: local
default_model: llama3.3:70b-instruct-q8_0

edge_extraction:
  model: llama3.3:70b-instruct-q8_0

reflexion:
  model: llama3.3:70b-instruct-q8_0

summarization:
  model: llama3.3:70b-instruct-q8_0
```

## Running the Example

1. Set up your environment variables in a `.env` file:
   ```
   NEO4J_URI=bolt://localhost:7687
   NEO4J_USER=neo4j
   NEO4J_PASSWORD=graphiti
   DEFAULT_DATABASE=local-ai
   OLLAMA_ENDPOINT=http://localhost:11434/v1
   OLLAMA_EMBEDDINGS_ENDPOINT=http://localhost:11434/api/embeddings
   ```

2. Run the example script:
   ```bash
   python examples/tuned_llm_manager/use_graphiti_with_tuned_llm.py
   ```

## What the Example Does

1. **Initializes TunedLLMManager** with a specific group ID
2. **Configures Graphiti** to use the TunedLLMManager for both LLM and cross-encoder
3. **Adds an episode** to the graph using the TunedLLMManager
4. **Performs a search** using the TunedLLMManager
5. **Tests direct LLM interaction** with the TunedLLMManager

## Debugging Configuration

You can use the `tune-llm-config-check` script to debug and visualize the configuration:

```bash
# Show configuration for a specific prompt type
./scripts/tune-llm-config-check show --prompt-type node_extraction

# Show all configurations
./scripts/tune-llm-config-check show

# Show detailed inheritance chain
./scripts/tune-llm-config-check show --verbose

# Compare configurations between groups
./scripts/tune-llm-config-check compare --prompt-type node_extraction --group1 default --group2 test_group
```

## Benefits Over Direct Client Usage

Using the TunedLLMManager instead of directly using OllamaClient provides several benefits:

1. **Automatic client selection** based on prompt type and configuration
2. **Parameter tuning** based on the context (prompt type, content length, etc.)
3. **Health checking and fallbacks** for robust operation
4. **Group-specific configurations** for different use cases
5. **Centralized configuration management** for easier maintenance

This makes it easier to manage multiple LLM clients and models, and to tune parameters based on the specific prompt type and content.
