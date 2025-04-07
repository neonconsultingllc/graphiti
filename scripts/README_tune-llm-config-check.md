# tune-llm-config-check

A command-line tool for debugging and visualizing TunedLLMManager configurations.

## Features

- **Show Resolved Configuration**: See the actual settings that would be used for a specific group ID and prompt type
- **View Inheritance Chain**: Understand which configuration files are being loaded and in what order
- **Validate Required Fields**: Check if all required parameters are present in the configuration
- **Simulate Requests**: See exactly what the TunedLLMManager would do with a given request
- **Compare Configurations**: Compare settings between different groups
- **Export as JSON**: Export the resolved configuration as JSON for further processing

## Installation

The script requires the following Python packages:
- rich
- rich-click
- pyyaml
- setuptools (optional, for package resource loading)

Install them with:

```bash
pip install rich rich-click pyyaml setuptools
```

## Usage

### Show Configuration

Show the resolved configuration for a specific prompt type and group:

```bash
./tune-llm-config-check show --prompt-type node_extraction --group group_123
```

Or show configurations for all prompt types:

```bash
./tune-llm-config-check show
```

You can also show all configurations for a specific group:

```bash
./tune-llm-config-check show --group group_123
```

Use the verbose flag to show the configuration inheritance chain for each prompt type, including what values each file sets. Values that actually affect the final configuration are highlighted in green with an arrow, while overridden values are dimmed:

```bash
./tune-llm-config-check show --verbose
```

You can also use the verbose flag with a specific prompt type:

```bash
./tune-llm-config-check show --prompt-type node_extraction --verbose
```

The output will show:

- A title panel with the prompt type and group
- The selected client, instance, and model
- The configuration inheritance chain with file paths and their status
- The resolved configuration as a table
- Any warnings about missing required fields

### Simulate Request

Simulate a request to the TunedLLMManager:

```bash
./tune-llm-config-check simulate --prompt-type edge_extraction --group group_456 --verbose
```

### Compare Configurations

Compare configurations between two groups:

```bash
./tune-llm-config-check compare --prompt-type node_extraction --group1 group_123 --group2 group_456
```

### Export as JSON

Export the configuration as JSON:

```bash
./tune-llm-config-check json --prompt-type node_extraction --group group_123 --output config.json
```

## Examples

### Check Default Configuration

```bash
./tune-llm-config-check show --prompt-type node_extraction
```

### Check Group-Specific Configuration

```bash
./tune-llm-config-check show --prompt-type edge_extraction --group group_123
```

### Compare Default and Group-Specific Configurations

```bash
./tune-llm-config-check compare --prompt-type summarization --group1 default --group2 group_123
```

### Verbose Simulation

```bash
./tune-llm-config-check simulate --prompt-type reflexion --group group_456 --verbose
```
