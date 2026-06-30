"""Mem0 客户端统一入口。

只负责一件事：从环境变量读取凭证，创建 MemoryClient 单例。
所有业务模块通过 `get_mem0_client()` 获取 client，不直接接触凭证。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from mem0 import MemoryClient

from apps.runtime.secret_resolver import resolve_runtime_secret


@lru_cache(maxsize=1)
def get_mem0_client() -> MemoryClient:
    """获取 Mem0 客户端单例。

    从环境变量 MEM0_API_KEY 读取凭证；若当前进程尚未加载环境，
    会先尝试加载项目根目录 `.env`，再尝试加载 `~/.hermes/.env`，
    最后回退到 Settings 管理的 DB secret。
    使用 lru_cache 确保整个进程生命周期只创建一个 client 实例。
    """
    project_root = Path(__file__).resolve().parents[3]
    load_dotenv(project_root / ".env", override=False)
    load_dotenv(Path.home() / ".hermes" / ".env", override=False)

    api_key = resolve_runtime_secret("MEM0_API_KEY") or ""
    if not api_key:
        raise RuntimeError(
            "MEM0_API_KEY 未设置。请在 .env 或环境变量中配置 Mem0 API Key。"
        )
    return MemoryClient(api_key=api_key)
