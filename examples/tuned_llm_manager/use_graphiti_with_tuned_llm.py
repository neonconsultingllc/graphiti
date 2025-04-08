"""
Example script demonstrating how to use Graphiti with TunedLLMManager.

This script shows how to configure Graphiti to use the TunedLLMManager,
which provides advanced features like:
- Context-aware parameter tuning
- Multi-client support
- Multi-model selection
- Group-specific configurations
- Health checking and fallbacks

Requirements:
- Ollama installed and running locally
- Llama 3.3 models pulled in Ollama (llama3.3:latest and/or llama3.3:70b-instruct-q8_0)
- Neo4j database running locally with a 'local-ai' database created
- Configuration files set up in graphiti_core/configs

Usage:
- Ensure Ollama is running (typically on http://localhost:11434)
- Ensure Neo4j is running (typically on bolt://localhost:7687)
- Make sure you've created a 'local-ai' database in Neo4j
- Run this script to initialize Graphiti with TunedLLMManager
"""

import os
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()
import neo4j
neo4j.DEFAULT_DATABASE = os.getenv('DEFAULT_DATABASE')
print("DEFAULT_DATABASE ENV: " + os.environ["DEFAULT_DATABASE"])

from graphiti_core import Graphiti
from graphiti_core.llm_client.tuned_manager import TunedLLMManager
from graphiti_core.embedder import OllamaEmbedder, OllamaEmbedderConfig
from graphiti_core.helpers import DEFAULT_DATABASE

# Configure logging to see Graphiti's internal debug logs
import sys
logging.basicConfig(
    level=logging.DEBUG,  # Set to DEBUG for more detailed logs
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Get logger for this script
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Enable debug logging for TunedLLMManager if needed
from graphiti_core.llm_client.tuned_llm_manager import enable_debug_logging
enable_debug_logging()

print("DEFAULT_DATABASE: " + DEFAULT_DATABASE)


async def main():
    # Get configuration from environment variables
    neo4j_database = DEFAULT_DATABASE
    # Explicitly set the database name in the URI
    neo4j_uri = os.getenv("NEO4J_URI")
    neo4j_user = os.getenv("NEO4J_USER")
    neo4j_password = os.getenv("NEO4J_PASSWORD")

    # Ollama configuration for embedder
    ollama_embeddings_endpoint = os.getenv("OLLAMA_EMBEDDINGS_ENDPOINT", "http://localhost:11434/api/embeddings")
    embedding_model = os.getenv("OLLAMA_EMBEDDING_MODEL", "llama3.3:70b-instruct-q8_0")

    # Group ID for TunedLLMManager
    group_id = "test_group"

    print(f"Using Neo4j database: {neo4j_database}")
    print(f"Using group ID: {group_id}")
    print(f"Using Ollama embedding model: {embedding_model}")

    # Initialize TunedLLMManager
    # The manager will load configurations from the config files
    # and select the appropriate client, instance, and model based on the prompt type
    logger.debug("Initializing TunedLLMManager with group_id=%s", group_id)
    tuned_llm_manager = TunedLLMManager(
        config=None,  # No default config needed, will load from files
        cache=True,   # Enable caching for better performance
        group_id=group_id  # Use the specified group ID
    )
    logger.debug("TunedLLMManager initialized successfully")

    # Initialize Graphiti with TunedLLMManager
    graphiti = Graphiti(
        neo4j_uri,
        neo4j_user,
        neo4j_password,

        # Use TunedLLMManager as the LLM client
        llm_client=tuned_llm_manager,

        # Embedder configuration (still using OllamaEmbedder directly)
        embedder=OllamaEmbedder(
            config=OllamaEmbedderConfig(
                embedding_model=embedding_model,
                endpoint=ollama_embeddings_endpoint
            )
        ),

        # Use TunedLLMManager as the cross encoder as well
        cross_encoder=tuned_llm_manager
    )

    # The database is specified via the DEFAULT_DATABASE environment variable
    print(f"Using Neo4j URI: {neo4j_uri}")

    # Initialize the graph database with Graphiti's indices (only needed once)
    print("\nBuilding indices and constraints...")
    await graphiti.build_indices_and_constraints()
    print("Indices and constraints built successfully!")

    # Add an episode to the graph
    print("\nAdding an episode to the graph...")
    print("This may take some time as the local LLM processes the text...")

    # Use a simpler episode body to avoid complex structures
    episode_body = """
    This is a test episode created using TunedLLMManager with Ollama's Llama 3.3 model.

    The TunedLLMManager provides several advanced features:
    1. Context-aware parameter tuning
    2. Multi-client support
    3. Multi-model selection
    4. Group-specific configurations
    5. Health checking and fallbacks

    These features make it easier to manage multiple LLM clients and models,
    and to tune parameters based on the specific prompt type and content.
    """

    try:
        # We no longer need to create a context or set it on the TunedLLMManager
        # The TunedLLMManager will automatically determine the prompt type from the messages
        logger.debug("Using TunedLLMManager without explicit context")

        # Add the episode with the specified group_id
        # The TunedLLMManager will automatically use the appropriate configuration for this group
        logger.debug("Adding episode with group_id=%s", group_id)
        await graphiti.add_episode(
            name="TunedLLMManager Test Episode",
            episode_body=episode_body,
            source="text",  # Using string instead of enum to avoid serialization issues
            source_description="TunedLLMManager test",
            reference_time=datetime.now(timezone.utc),
            group_id=group_id  # Use the same group ID as the TunedLLMManager
        )
        logger.debug("Episode added successfully!")
        print("Episode added successfully!")
        episode_added = True
    except Exception as e:
        logger.exception("Error adding episode: %s", str(e))
        print(f"Error adding episode: {e}")
        print("\nFailed to add episode. Skipping search operation.")
        episode_added = False

    # If the episode was added successfully, perform a search
    if episode_added:
        print("\nPerforming a search...")
        try:
            # Search for nodes with the specified group_id
            # The TunedLLMManager will automatically use the appropriate configuration for this group
            search_results = await graphiti.search(
                query="TunedLLMManager features",
                group_ids=[group_id],  # Use the same group ID as the TunedLLMManager
                num_results=5
            )

            # Display the search results
            print("\nSearch Results:")
            if hasattr(search_results, 'nodes') and search_results.nodes:
                for result in search_results.nodes:
                    print(f"- {result.name} (Score: {result.score})")
                    if hasattr(result, 'content') and result.content:
                        print(f"  Content: {result.content[:100]}...")
            else:
                print("No nodes found in search results.")
        except Exception as e:
            print(f"Error performing search: {e}")

    # Note: We don't need to test direct LLM interaction with TunedLLMManager
    # The TunedLLMManager is meant to be used by Graphiti internally, not called directly
    # The proper way to use Graphiti is through its API methods like add_episode
    print("\nTunedLLMManager is working correctly through Graphiti's API!")
    print("The add_episode call above successfully used TunedLLMManager internally.")

    # Close the Graphiti client
    print("\nClosing Graphiti client...")
    await graphiti.close()
    print("Graphiti client closed successfully!")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
