"""
Copyright 2024, Zep Software, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import asyncio
import aiohttp
import logging
from collections.abc import Iterable
from pydantic import Field

from .client import EmbedderClient, EmbedderConfig

DEFAULT_EMBEDDING_MODEL = 'llama3.3:70b-instruct-q8_0'
DEFAULT_EMBEDDING_ENDPOINT = 'http://localhost:11434/api/embeddings'

logger = logging.getLogger(__name__)

class OllamaEmbedderConfig(EmbedderConfig):
    embedding_model: str = Field(default=DEFAULT_EMBEDDING_MODEL)
    api_key: str | None = None
    endpoint: str = Field(default=DEFAULT_EMBEDDING_ENDPOINT)
    max_retries: int = Field(default=5)


class OllamaEmbedder(EmbedderClient):
    """
    Ollama Embedder Client
    
    This client uses the Ollama API to generate embeddings.
    """

    def __init__(self, config: OllamaEmbedderConfig | None = None):
        if config is None:
            config = OllamaEmbedderConfig()
        self.config = config
        self.model = config.embedding_model
        self.endpoint = config.endpoint
        self.api_key = config.api_key
        self.max_retries = config.max_retries

    async def create(
        self, input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]]
    ) -> list[float]:
        """
        Create embeddings for the given input data using Ollama API.
        
        Args:
            input_data: The text to embed. Can be a string or a list of strings.
            
        Returns:
            A list of floats representing the embedding vector.
        """
        # Convert input to string if it's not already
        if isinstance(input_data, str):
            text = input_data
        elif isinstance(input_data, list) and len(input_data) > 0:
            if isinstance(input_data[0], str):
                # Just use the first string if a list of strings is provided
                text = input_data[0]
            else:
                # Convert to string if it's a list of numbers
                text = str(input_data)
        else:
            # Convert any other iterable to string
            text = str(input_data)
            
        # Get embedding from Ollama API
        embedding = await self._get_embedding(text)
        
        # Ensure the embedding is the correct dimension
        return embedding[:self.config.embedding_dim]
    
    async def _get_embedding(self, prompt: str) -> list[float]:
        """
        Internal method to call the Ollama embeddings endpoint for a single prompt.
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
        }
        
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            
        retries = 0
        while retries < self.max_retries:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        self.endpoint, json=payload, headers=headers, timeout=60.0
                    ) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            logger.error(f"HTTP error {response.status}: {error_text}")
                            retries += 1
                            await asyncio.sleep(min(2**retries, 60))
                            continue
                            
                        data = await response.json()
                        return data["embedding"]
            except Exception as e:
                logger.error(f"Error on attempt {retries + 1}: {e}")
                retries += 1
                await asyncio.sleep(min(2**retries, 60))
                
        raise Exception(
            f"Failed to embed text using model {self.model} after {self.max_retries} retries"
        )
