"""
Gemini CLI MCP Server Wrapper with Async Support
将 Gemini CLI 封装为符合 MCP 协议的 server，支持异步任务
"""

from .server import main

__version__ = "0.1.0"
__all__ = ["main"]