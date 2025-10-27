"""
OpenRouter-specific client that properly handles structured output.
"""

import json
import logging
import re
import typing
from typing import ClassVar

import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from graphiti_core.llm_client.client import get_extraction_language_instruction, LLMClient
from graphiti_core.llm_client.config import DEFAULT_MAX_TOKENS, LLMConfig, ModelSize
from graphiti_core.llm_client.errors import RateLimitError, RefusalError
from graphiti_core.prompts.models import Message


logger = logging.getLogger('graphiti_bridge.sync')


class InfrastructureError(Exception):
    """Raised when the service provider has infrastructure issues"""
    pass


def _parse_html_error(html_content: str) -> str:
    """Parse HTML error page to extract meaningful error information"""
    # Look for specific error patterns with priority order
    error_code_match = re.search(r'Error (\d+)', html_content, re.IGNORECASE)
    description_match = re.search(r'Worker exceeded resource limits', html_content, re.IGNORECASE)
    
    if error_code_match and description_match:
        return f"OpenRouter infrastructure error: Error {error_code_match.group(1)} - Worker exceeded resource limits"
    elif error_code_match:
        return f"OpenRouter infrastructure error: Error {error_code_match.group(1)}"
    elif description_match:
        return f"OpenRouter infrastructure error: Worker exceeded resource limits"
    else:
        # Fallback to generic HTML error detection
        return "OpenRouter infrastructure error: HTML error page detected - Service temporarily unavailable"

DEFAULT_MODEL = 'openai/gpt-4o-mini'

# Global response counter for aggregated logging
_global_response_count = 0
_last_provider = None
_last_model = None


class OpenRouterClient(LLMClient):
    """
    OpenRouter-specific client that properly handles structured output.

    Unlike OpenAI, OpenRouter requires:
    1. json_schema format (not json_object) for complex schemas
    2. provider preferences in extra_body for structured output routing
    """

    MAX_RETRIES: ClassVar[int] = 2
    _class_response_count: ClassVar[int] = 0
    
    def __init__(
        self, config: LLMConfig | None = None, cache: bool = False, client: typing.Any = None,
        preferred_providers: list[str] | None = None, excluded_providers: list[str] | None = None
    ):
        if cache:
            raise NotImplementedError(
                'Caching is not implemented for OpenRouter')

        if config is None:
            config = LLMConfig()

        super().__init__(config, cache)
        
        # Store provider preferences
        self.preferred_providers = preferred_providers
        self.excluded_providers = excluded_providers

        if client is None:
            self.client = AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.base_url or "https://openrouter.ai/api/v1"
            )
        else:
            self.client = client

    def _get_model_for_size(self, model_size: ModelSize) -> str:
        """Get appropriate model based on size requirement"""
        logger = logging.getLogger('graphiti_bridge.sync')
        
        if model_size == ModelSize.small:
            # Try to get small model from instance or config
            small_model = getattr(self, 'small_model', None)
            if not small_model and hasattr(self, 'config'):
                small_model = getattr(self.config, 'small_model', None)
            
            if not small_model:
                logger.info("No small_model configured for OpenRouter, using main model as fallback")
                # Fallback to main model, then default
                main_model = getattr(self, 'model', None)
                if not main_model and hasattr(self, 'config'):
                    main_model = getattr(self.config, 'model', None)
                return main_model if main_model else DEFAULT_MODEL
            return small_model
        else:
            # Use main model
            main_model = getattr(self, 'model', None)
            if not main_model and hasattr(self, 'config'):
                main_model = getattr(self.config, 'model', None)
            return main_model if main_model else DEFAULT_MODEL

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, typing.Any]:
        logger = logging.getLogger('graphiti_bridge.sync')
        
        openai_messages: list[ChatCompletionMessageParam] = []
        for m in messages:
            m.content = self._clean_input(m.content)
            if m.role == 'user':
                openai_messages.append({'role': 'user', 'content': m.content})
            elif m.role == 'system':
                openai_messages.append(
                    {'role': 'system', 'content': m.content})

        try:
            # Prepare request parameters
            request_params = {
                'model': self._get_model_for_size(model_size),
                'messages': openai_messages,
                'temperature': self.temperature,
                'max_tokens': self.max_tokens,
            }

            # For OpenRouter, we need different handling based on schema complexity
            if response_model is not None:
                # Use json_schema format with provider preferences for structured output
                schema = response_model.model_json_schema()

                # CRITICAL: OpenRouter requires additionalProperties: false and required array for all objects
                def fix_schema_for_openrouter(obj):
                    if isinstance(obj, dict):
                        if obj.get('type') == 'object':
                            obj['additionalProperties'] = False
                            # Add required field with all property names if properties exist
                            if 'properties' in obj and obj['properties']:
                                obj['required'] = list(
                                    obj['properties'].keys())
                        for value in obj.values():
                            fix_schema_for_openrouter(value)
                    elif isinstance(obj, list):
                        for item in obj:
                            fix_schema_for_openrouter(item)

                fix_schema_for_openrouter(schema)

                request_params['response_format'] = {
                    'type': 'json_schema',
                    'json_schema': {
                        'name': response_model.__name__,
                        'strict': True,
                        'schema': schema
                    }
                }
                # CRITICAL: OpenRouter needs provider preferences for structured output
                provider_config = {
                    'require_parameters': True
                }
                
                # Add preferred providers if specified
                if self.preferred_providers:
                    provider_config['order'] = self.preferred_providers
                    
                # Add excluded providers if specified
                if self.excluded_providers:
                    provider_config['ignore'] = self.excluded_providers
                    
                request_params['extra_body'] = {
                    'provider': provider_config
                }
            else:
                # Simple JSON object for basic cases
                request_params['response_format'] = {'type': 'json_object'}

            # Make the API call
            response = await self.client.chat.completions.create(**request_params)
            
            # Aggregated logging to reduce spam
            provider = getattr(response, 'provider', 'Unknown')
            model = getattr(response, 'model', 'Unknown')
            
            global _global_response_count
            _global_response_count += 1
            
            # Log aggregated response (first call, then every 5th)
            if _global_response_count == 1:
            elif _global_response_count % 5 == 0:
            
            result = response.choices[0].message.content or ''
            
            # Check if response is HTML (Cloudflare/infrastructure error)
            if result.strip().startswith(('<!DOCTYPE html>', '<html')):
                error_msg = _parse_html_error(result)
                logger.error(error_msg)
                raise InfrastructureError(error_msg)
            
            return json.loads(result)

        except openai.RateLimitError as e:
            raise RateLimitError from e
        except json.JSONDecodeError as e:
            # Check if JSON decode error is due to HTML content
            content = getattr(e, 'doc', '') or str(e)
            if '<!DOCTYPE html>' in content or '<html' in content:
                error_msg = _parse_html_error(content)
                logger.error(error_msg)
                raise InfrastructureError(error_msg)
            logger.error(f'Error in generating LLM response: {e}')
            raise
        except InfrastructureError:
            raise  # Re-raise infrastructure errors without modification
        except Exception as e:
            logger.error(f'Error in generating LLM response: {e}')
            raise

    async def generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int | None = None,
        model_size: ModelSize = ModelSize.medium,
        group_id: str | None = None,
        prompt_name: str | None = None,
    ) -> dict[str, typing.Any]:
        logger = logging.getLogger('graphiti_bridge.sync')
        
        if max_tokens is None:
            max_tokens = self.max_tokens

        retry_count = 0
        last_error = None

        # For OpenRouter, DON'T add schema to prompt when using structured output
        # The json_schema format handles this automatically
        if response_model is None:
            # Only add schema to prompt for simple JSON object requests
            # (This maintains compatibility with the original behavior)
            pass

        # Add multilingual extraction instructions
        messages[0].content += get_extraction_language_instruction(group_id)

        while retry_count <= self.MAX_RETRIES:
            try:
                response = await self._generate_response(
                    messages, response_model, max_tokens=max_tokens, model_size=model_size
                )
                return response
            except (RateLimitError, RefusalError):
                raise
            except (openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError):
                raise
            except InfrastructureError:
                raise
            except Exception as e:
                last_error = e

                if retry_count >= self.MAX_RETRIES:
                    logger.error(
                        f'Max retries ({self.MAX_RETRIES}) exceeded. Last error: {e}')
                    raise

                retry_count += 1

                error_context = (
                    f'The previous response attempt was invalid. '
                    f'Error type: {e.__class__.__name__}. '
                    f'Error details: {str(e)}. '
                    f'Please try again with a valid response, ensuring the output matches '
                    f'the expected format and constraints.'
                )

                error_message = Message(role='user', content=error_context)
                messages.append(error_message)
                logger.warning(
                    f'Retrying after application error (attempt {retry_count}/{self.MAX_RETRIES}): {e}'
                )

        raise last_error or Exception(
            'Max retries exceeded with no specific error')