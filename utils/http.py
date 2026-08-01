import asyncio
from aiohttp import ClientSession, TCPConnector
from utils.config import config

_shared_session: ClientSession | None = None
_shared_lock = asyncio.Lock()

async def get_shared_session() -> ClientSession:
    """Return a shared aiohttp ClientSession (create if necessary)."""
    global _shared_session
    async with _shared_lock:
        if _shared_session is None or _shared_session.closed:
            connector = TCPConnector(ssl=False, limit=getattr(config, 'speed_test_limit', 5))
            _shared_session = ClientSession(connector=connector, trust_env=True)
    return _shared_session

async def close_shared_session() -> None:
    """Close the shared session if exists."""
    global _shared_session
    async with _shared_lock:
        if _shared_session is not None and not _shared_session.closed:
            await _shared_session.close()
            _shared_session = None
