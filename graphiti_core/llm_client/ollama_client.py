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

import json
import logging
import typing
from typing import ClassVar

from ollama import AsyncClient as OllamaAsyncClient
from pydantic import BaseModel

from ..prompts.models import Message
from .client import LLMClient
from .config import DEFAULT_MAX_TOKENS, LLMConfig
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

DEFAULT_MODEL = 'llama3.3:70b-instruct-q8_0'


class OllamaClient(LLMClient):
    """
    OllamaClient is a client class for interacting with Ollama's language models via the native Python client.

    This class extends the LLMClient and provides methods to initialize the client,
    and generate responses from the language model.

    Attributes:
        model (str): The model name to use for generating responses.
        temperature (float): The temperature to use for generating responses.
        max_tokens (int): The maximum number of tokens to generate in a response.
        client (OllamaAsyncClient): The Ollama async client instance.
    """

    # Class-level constants
    MAX_RETRIES: ClassVar[int] = 2

    def __init__(
        self,
        config: LLMConfig | None = None,
        cache: bool = False,
        client: typing.Any = None,  # Not used, but kept for compatibility
        max_tokens: int = DEFAULT_MAX_TOKENS,  # Not used, but kept for compatibility
    ):
        """
        Initialize the OllamaClient with the provided configuration and cache setting.

        Args:
            config (LLMConfig | None): The configuration for the LLM client, including model, base URL, temperature, and max tokens.
            cache (bool): Whether to use caching for responses. Defaults to False.
            client (Any | None): Not used, kept for compatibility with the LLMClient interface.
            max_tokens (int): Not used directly, kept for compatibility.
        """
        # removed caching to simplify the `generate_response` override
        if cache:
            raise NotImplementedError('Caching is not implemented for Ollama')

        if config is None:
            config = LLMConfig()

        super().__init__(config, cache)

        # Create an Ollama AsyncClient instance
        # The default Ollama API endpoint is http://localhost:11434
        # We don't use the base_url from config because it might include '/v1' which is for OpenAI compatibility
        self.client = OllamaAsyncClient(host="http://localhost:11434")

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict[str, typing.Any]:
        """
        Generate a response from Ollama using the native Python client.

        This method uses the AsyncClient.chat method which provides better control over the output format.
        """
        # Convert Graphiti Message objects to Ollama message format
        ollama_messages = []
        for m in messages:
            m.content = self._clean_input(m.content)
            ollama_messages.append({
                'role': m.role,
                'content': m.content
            })

        try:
            # Prepare parameters for the Ollama API call
            params = {
                'model': self.model or DEFAULT_MODEL,
                'messages': ollama_messages,
                'stream': False  # We don't want streaming for this method
            }

            # Add options parameter with temperature and num_predict
            options = {}
            if response_model is None and self.temperature is not None:
                options['temperature'] = self.temperature
            else:
                options['temperature'] = 0.0  # Lower temperature for structured output

            if max_tokens or self.max_tokens:
                options['num_predict'] = max_tokens or self.max_tokens

            if options:
                params['options'] = options

            # If a response model is provided, request JSON format with schema
            if response_model is not None:
                schema = response_model.model_json_schema()
                params['format'] = schema
                logger.debug(f"Requesting JSON format from Ollama with schema: {schema}")

            # Call the Ollama API using the AsyncClient
            logger.debug(f"Calling Ollama API with params: {params}")
            response = await self.client.chat(**params)

            # Extract the content from the response
            content = response['message']['content']
            logger.debug(f"Raw content from Ollama: {content}")

            # If a response model is provided, try to parse the content as JSON
            if response_model is not None and content:
                try:
                    # Try to parse as JSON if a response model is provided
                    parsed_content = json.loads(content)
                    logger.debug(f"Parsed JSON content: {parsed_content}")

                    return parsed_content
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse JSON: {e}")
                    # If parsing fails, return the content as a string
                    return {"content": content}
            else:
                # Return the content as a string
                logger.debug(f"No response model provided, returning content as string")
                return {"content": content}

        except Exception as e:
            logger.error(f'Error in generating LLM response: {e}')
            raise

    async def generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict[str, typing.Any]:
        """
        Generate a response from the language model based on the provided messages.

        This method includes retry logic for handling errors.
        """
        retry_count = 0
        last_error = None

        # If a response model is provided, add instructions to format the response as JSON
        if response_model is not None:
            # Add simple instructions to format as JSON according to the schema
            instructions = f"Respond with a JSON object that matches this schema."
            messages.append(Message(role="user", content=instructions))
            logger.debug(f"Added JSON formatting instructions")

        while retry_count <= self.MAX_RETRIES:
            try:
                logger.debug(f"Generating response (attempt {retry_count + 1}/{self.MAX_RETRIES + 1})")
                response = await self._generate_response(messages, response_model, max_tokens)
                return response
            except Exception as e:
                last_error = e
                logger.error(f"Error generating response: {e}")

                # Don't retry if we've hit the max retries
                if retry_count >= self.MAX_RETRIES:
                    logger.error(f'Max retries ({self.MAX_RETRIES}) exceeded. Last error: {e}')
                    raise

                retry_count += 1

                # Construct a detailed error message for the LLM
                error_context = (
                    f'The previous response attempt was invalid. '
                    f'Error type: {e.__class__.__name__}. '
                    f'Error details: {str(e)}. '
                    f'Please try again with a valid response, ensuring the output matches '
                    f'the expected format and constraints. '
                    f'Remember: Neo4j does not support nested objects as property values.'
                )

                error_message = Message(role='user', content=error_context)
                messages.append(error_message)
                logger.warning(
                    f'Retrying after application error (attempt {retry_count}/{self.MAX_RETRIES}): {e}'
                )

        # If we somehow get here, raise the last error
        raise last_error or Exception('Max retries exceeded with no specific error')
