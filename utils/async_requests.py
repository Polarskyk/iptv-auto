import asyncio
from aiohttp import ClientSession
from bs4 import BeautifulSoup
from typing import Optional
from utils.http import get_shared_session
from utils.config import config


async def fetch_text(url: str, timeout: int = 30, proxy: Optional[str] = None) -> str:
    session: ClientSession = await get_shared_session()
    try:
        async with session.get(url, timeout=timeout, proxy=proxy) as resp:
            resp.raise_for_status()
            text = await resp.text()
            return text
    except Exception:
        raise


async def get_soup_aiohttp(url: str, timeout: int = 30, proxy: Optional[str] = None) -> BeautifulSoup:
    text = await fetch_text(url, timeout=timeout, proxy=proxy)
    loop = asyncio.get_running_loop()
    # parsing is CPU-bound-ish; offload to thread pool
    soup = await loop.run_in_executor(None, lambda: BeautifulSoup(text, "html.parser"))
    return soup
