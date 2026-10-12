"""LLM provider configuration — reads from environment / .env."""

from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ProviderConfig:
    """Configuration for a single LLM provider."""

    name: str
    api_key: str
    base_url: str
    default_model: str
    max_tokens: int = 4096
    timeout: float = 120.0
    default_reasoning_effort: str | None = None


@dataclass
class LLMConfig:
    """Top-level LLM configuration with provider registry."""

    default_provider: str = "cockpit"
    fallback_providers: tuple[str, ...] = ("jojocode",)
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
                default_model=os.getenv("LLM_COCKPIT_MODEL", "gpt-5.6-sol"),
                max_tokens=int(os.getenv("LLM_COCKPIT_MAX_TOKENS", "4096")),
                timeout=float(os.getenv("LLM_COCKPIT_TIMEOUT", "180")),
                default_reasoning_effort=os.getenv("LLM_COCKPIT_REASONING_EFFORT", "high"),
            )

        # JojoCode — Responses-compatible provider with hosted web_search.
        # Prefer explicit environment configuration. For local development, the
        # existing Cockpit account registry is a credential source so the same
        # account can be reused without copying its API key into the repository.
        jojocode_key = os.getenv("JOJOCODE_API_KEY", "").strip()
        jojocode_url = os.getenv("JOJOCODE_BASE_URL", "").strip()
        if not jojocode_key:
            discovered = _load_jojocode_from_cockpit()
            if discovered is not None:
                jojocode_key, discovered_url = discovered
                jojocode_url = jojocode_url or discovered_url
        if jojocode_key:
            providers["jojocode"] = ProviderConfig(
                name="jojocode",
                api_key=jojocode_key,
                base_url=jojocode_url or "https://max.jojocode.com/v1",
                default_model=os.getenv("LLM_JOJOCODE_MODEL", "gpt-5.6-sol"),
                max_tokens=int(os.getenv("LLM_JOJOCODE_MAX_TOKENS", "4096")),
                timeout=float(os.getenv("LLM_JOJOCODE_TIMEOUT", "180")),
                default_reasoning_effort=os.getenv("LLM_JOJOCODE_REASONING_EFFORT", "high"),
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

        # DeepSeek
        ds_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if ds_key:
            providers["deepseek"] = ProviderConfig(
                name="deepseek",
                api_key=ds_key,
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
                default_model=os.getenv("LLM_DEEPSEEK_MODEL", "deepseek-chat"),
                max_tokens=int(os.getenv("LLM_DEEPSEEK_MAX_TOKENS", "4096")),
                timeout=float(os.getenv("LLM_DEEPSEEK_TIMEOUT", "120")),
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

        fallback_providers = tuple(
            name
            for name in _provider_names(os.getenv("LLM_FALLBACK_PROVIDERS", "jojocode"))
            if name in providers and name != default_provider
        )

        return cls(
            default_provider=default_provider,
            fallback_providers=fallback_providers,
            providers=providers,
        )

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
    def provider_chain(self) -> list[str]:
        """Return the configured primary/backup chain, omitting unavailable providers."""
        chain = [self.default_provider, *self.fallback_providers]
        return list(dict.fromkeys(name for name in chain if name in self.providers))

    @property
    def is_configured(self) -> bool:
        return len(self.providers) > 0


def _provider_names(value: str) -> list[str]:
    return list(dict.fromkeys(name.strip() for name in value.split(",") if name.strip()))


def _load_jojocode_from_cockpit() -> tuple[str, str] | None:
    """Resolve an existing JojoCode account from Cockpit without exposing it."""
    for path in _cockpit_provider_files():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, list):
            continue
        for provider in payload:
            if not isinstance(provider, dict):
                continue
            name = str(provider.get("name") or "").strip().lower()
            base_url = str(provider.get("baseUrl") or provider.get("base_url") or "").strip()
            if "jojo" not in name or not base_url.rstrip("/").endswith("/v1"):
                continue
            for account in provider.get("apiKeys") or []:
                if not isinstance(account, dict):
                    continue
                api_key = str(account.get("apiKey") or "").strip()
                if api_key:
                    return api_key, base_url
    return None


def _cockpit_provider_files() -> list[Path]:
    candidates: list[Path] = []
    explicit = os.getenv("JOJOCODE_COCKPIT_PROVIDERS_FILE", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.append(Path.home() / ".antigravity_cockpit" / "codex_model_providers.json")
    try:
        windows_candidates = sorted(
            Path("/mnt/c/Users").glob("*/.antigravity_cockpit/codex_model_providers.json")
        )
        if len(windows_candidates) == 1:
            candidates.extend(windows_candidates)
    except OSError:
        pass
    return list(dict.fromkeys(candidates))
