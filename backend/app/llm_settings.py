"""Local, private LLM configuration. Secrets are never returned by the API."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

SETTINGS_PATH = Path(__file__).resolve().parents[2] / '.runtime' / 'llm-settings.json'
Provider = Literal['openai', 'anthropic', 'gemini', 'azure', 'bedrock', 'vertex_ai',
                   'ollama', 'lmstudio', 'openrouter', 'compatible', 'custom']
SECRET_FIELDS = ('api_key', 'aws_access_key_id', 'aws_secret_access_key',
                 'aws_session_token', 'vertex_credentials')


class LLMSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    provider: Provider = 'openai'
    model: str = Field('gpt-4o', min_length=1, max_length=256)
    base_url: str = Field('', max_length=2048)
    api_key: SecretStr = Field(default_factory=lambda: SecretStr(''))
    output_mode: Literal['tools', 'json'] = 'tools'
    api_version: str = Field('', max_length=100)
    aws_region_name: str = Field('', max_length=100)
    aws_access_key_id: SecretStr = Field(default_factory=lambda: SecretStr(''))
    aws_secret_access_key: SecretStr = Field(default_factory=lambda: SecretStr(''))
    aws_session_token: SecretStr = Field(default_factory=lambda: SecretStr(''))
    vertex_project: str = Field('', max_length=256)
    vertex_location: str = Field('', max_length=100)
    vertex_credentials: SecretStr = Field(default_factory=lambda: SecretStr(''))

    @field_validator('base_url')
    @classmethod
    def validate_url(cls, value: str) -> str:
        if value:
            try:
                parsed = urlsplit(value)
                valid = (parsed.scheme in ('http', 'https') and parsed.hostname
                         and not parsed.username and not parsed.password
                         and not parsed.query and not parsed.fragment)
                parsed.port  # Validate malformed ports too.
            except ValueError:
                valid = False
            if not valid:
                raise ValueError('Use an HTTP(S) base URL without credentials, query parameters, or fragments.')
        return value.rstrip('/')

    @field_validator(*SECRET_FIELDS)
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) > 32_000:
            raise ValueError('Credential is too long.')
        return value

    @field_validator('vertex_credentials')
    @classmethod
    def validate_vertex_credentials(cls, value: SecretStr) -> SecretStr:
        if value.get_secret_value():
            try:
                data = json.loads(value.get_secret_value())
                if not isinstance(data, dict) or data.get('type') != 'service_account':
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError('Enter a service account JSON object.') from None
        return value

    @model_validator(mode='after')
    def required_endpoint(self) -> 'LLMSettings':
        if self.provider in ('azure', 'compatible') and not self.base_url:
            raise ValueError('Enter the service base URL.')
        if self.provider == 'azure' and not self.api_version:
            raise ValueError('Enter the Azure API version for your deployment.')
        if self.provider == 'custom' and '/' not in self.model:
            raise ValueError('Use a LiteLLM provider/model identifier, for example mistral/your-model.')
        return self

    @property
    def configured(self) -> bool:
        return self.provider in ('ollama', 'lmstudio', 'compatible', 'custom', 'bedrock', 'vertex_ai') or bool(self.api_key.get_secret_value())

    def private_dict(self) -> dict:
        data = self.model_dump()
        for name in SECRET_FIELDS:
            data[name] = getattr(self, name).get_secret_value()
        return data

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.private_dict(), sort_keys=True).encode()).hexdigest()

    def public_dict(self) -> dict:
        data = self.model_dump(exclude=set(SECRET_FIELDS))
        data['configured'] = self.configured
        data['saved_credentials'] = {name: bool(getattr(self, name).get_secret_value()) for name in SECRET_FIELDS}
        return data

    def completion_kwargs(self) -> dict:
        provider = self.provider
        routed_provider = {'lmstudio': 'openai', 'compatible': 'openai', 'ollama': 'ollama_chat'}.get(provider, provider)
        # A model is an opaque provider ID; preserve slashes (e.g. OpenRouter IDs).
        model = self.model if provider == 'custom' else f'{routed_provider}/{self.model}'
        kwargs: dict = {'model': model, 'timeout': 90, 'num_retries': 0}
        base = self.base_url or {'ollama': 'http://127.0.0.1:11434',
                                 'lmstudio': 'http://127.0.0.1:1234/v1'}.get(provider, '')
        if base:
            kwargs['api_base'] = base
        if self.api_key.get_secret_value():
            kwargs['api_key'] = self.api_key.get_secret_value()
        elif provider in ('ollama', 'lmstudio', 'compatible'):
            # Do not accidentally reuse OPENAI_API_KEY for an unauthenticated local endpoint.
            kwargs['api_key'] = 'local-no-key'
        if provider == 'azure':
            kwargs['api_version'] = self.api_version
        if provider == 'bedrock':
            for name in ('aws_region_name', 'aws_access_key_id', 'aws_secret_access_key', 'aws_session_token'):
                value = getattr(self, name)
                value = value.get_secret_value() if isinstance(value, SecretStr) else value
                if value:
                    kwargs[name] = value
        if provider == 'vertex_ai':
            for name in ('vertex_project', 'vertex_location', 'vertex_credentials'):
                value = getattr(self, name)
                value = value.get_secret_value() if isinstance(value, SecretStr) else value
                if value:
                    kwargs[name] = value
        return kwargs


class SettingsUpdate(LLMSettings):
    clear_credentials: bool = False


def get_settings() -> LLMSettings:
    if SETTINGS_PATH.exists():
        try:
            return LLMSettings.model_validate_json(SETTINGS_PATH.read_text())
        except (ValueError, OSError):
            # A broken saved file must not prevent deterministic source analysis.
            return LLMSettings()
    return LLMSettings(api_key=os.environ.get('OPENAI_API_KEY', ''),
                       model=os.environ.get('OPENAI_MODEL') or 'gpt-4o',
                       base_url=os.environ.get('OPENAI_BASE_URL', ''))


def resolve_update(update: SettingsUpdate) -> LLMSettings:
    data = update.model_dump(exclude={'clear_credentials'})
    previous = get_settings()
    # Never forward a saved credential to a different service or cloud account.
    identity = ('provider', 'base_url', 'api_version', 'aws_region_name', 'vertex_project', 'vertex_location')
    same_service = all(getattr(update, name) == getattr(previous, name) for name in identity)
    for name in SECRET_FIELDS:
        if not update.clear_credentials and same_service and not getattr(update, name).get_secret_value():
            data[name] = getattr(previous, name)
    return LLMSettings.model_validate(data)


def save_settings(settings: LLMSettings) -> None:
    SETTINGS_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix='.llm-', dir=SETTINGS_PATH.parent)
        with os.fdopen(fd, 'w') as file:
            os.fchmod(file.fileno(), 0o600)
            json.dump(settings.private_dict(), file)
        os.replace(temporary, SETTINGS_PATH)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
