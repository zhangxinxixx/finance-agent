"""LLM provider configuration — reads from environment / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderConfig:
    """Configuration for a single LLM provider."""

    name: str
    api_key: str
    base_url: str
    default_model: str
    max_tokens: int = 4096
    timeout: float = 120.0


@dataclass
class LLMConfig:
    """Top-level LLM configuration with provider registry."""

    default_provider: str = "cockpit"
    providers: dict[str, ProviderConfig] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> LLMConfig:
        """Build config from environment variables / .env file."""
        from dotenv import load_dotenv

        load_dotenv()

        providers: dict[str, ProviderConfig] = {}

        # Cockpit (Sub2API) — primary provider
        cockpit_key = os.getenv("COCKPIT_API_KEY", "").strip()
        cockpit_url = os.getenv("COCKPIT_BASE_URL", "").strip()
        if not cockpit_key or not cockpit_url:
            # Try reading from hermes config
            try:
                import yaml
                hermes_config_path = os.path.expanduser("~/.hermes/config.yaml")
                if os.path.exists(hermes_config_path):
                    with open(hermes_config_path) as f:
                        hermes_config = yaml.safe_load(f)
                    for provider in hermes_config.get("custom_providers", []):
                        if provider.get("name") == "cockpit-codex":
                            cockpit_key = cockpit_key or provider.get("api_key", "")
                            cockpit_url = cockpit_url or provider.get("base_url", "")
                            break
            except Exception:
                pass
        if cockpit_key and cockpit_url:
            providers["cockpit"] = ProviderConfig(
                name="cockpit",
                api_key=cockpit_key,
                base_url=cockpit_url,
                default_model=os.getenv("LLM_COCKPIT_MODEL", "gpt-5.5"),
                max_tokens=int(os.getenv("LLM_COCKPIT_MAX_TOKENS", "4096")),
                timeout=float(os.getenv("LLM_COCKPIT_TIMEOUT", "180")),
            )

        # DashScope (Alibaba Qwen)
        ds_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        if ds_key:
            providers["dashscope"] = ProviderConfig(
                name="dashscope",
                api_key=ds_key,
                base_url=os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                default_model=os.getenv("LLM_DASHSCOPE_MODEL", "qwen-plus"),
                max_tokens=int(os.getenv("LLM_DASHSCOPE_MAX_TOKENS", "4096")),
                timeout=float(os.getenv("LLM_DASHSCOPE_TIMEOUT", "120")),
            )

        # Xiaomi MiMo
        mimo_key = os.getenv("XIAOMI_MIMO_API_KEY", "").strip()
        if mimo_key:
            providers["mimo"] = ProviderConfig(
                name="mimo",
                api_key=mimo_key,
                base_url=os.getenv("XIAOMI_MIMO_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1"),
                default_model=os.getenv("LLM_MIMO_MODEL", "mimo-v2.5-pro"),
                max_tokens=int(os.getenv("LLM_MIMO_MAX_TOKENS", "4096")),
                timeout=float(os.getenv("LLM_MIMO_TIMEOUT", "120")),
            )

        # OpenAI (direct or via proxy)
        oai_key = os.getenv("OPENAI_API_KEY", "").strip()
        if oai_key:
            providers["openai"] = ProviderConfig(
                name="openai",
                api_key=oai_key,
                base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                default_model=os.getenv("LLM_OPENAI_MODEL", "gpt-4.1-mini"),
                max_tokens=int(os.getenv("LLM_OPENAI_MAX_TOKENS", "4096")),
                timeout=float(os.getenv("LLM_OPENAI_TIMEOUT", "120")),
            )

        default_provider = os.getenv("LLM_DEFAULT_PROVIDER", "cockpit")
        if default_provider not in providers:
            # Fallback to first available provider
            default_provider = next(iter(providers)) if providers else ""

        return cls(default_provider=default_provider, providers=providers)

    def get_provider(self, name: str | None = None) -> ProviderConfig:
        """Get provider config by name, or default."""
        key = name or self.default_provider
        if key not in self.providers:
            available = ", ".join(self.providers.keys()) or "(none)"
            raise ValueError(f"LLM provider '{key}' not configured. Available: {available}")
        return self.providers[key]

    @property
    def available_providers(self) -> list[str]:
        return list(self.providers.keys())

    @property
    def is_configured(self) -> bool:
        return len(self.providers) > 0
