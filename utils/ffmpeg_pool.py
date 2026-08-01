import asyncio
from typing import Tuple, Optional
from utils.config import config
import subprocess
import threading

_pool_semaphore: asyncio.Semaphore | None = None


def _get_pool_semaphore() -> asyncio.Semaphore:
    global _pool_semaphore
    if _pool_semaphore is None:
        limit = max(1, int(getattr(config, 'speed_test_limit', 5)))
        _pool_semaphore = asyncio.Semaphore(limit)
    return _pool_semaphore


async def run_ffmpeg(args: list[str], timeout: int) -> Tuple[Optional[bytes], Optional[bytes]]:
    """Run ffmpeg/ffprobe via asyncio subprocess, limited by semaphore.

    Returns (stdout, stderr) as bytes or (None, None) on failure.
    """
    sem = _get_pool_semaphore()
    proc = None
    try:
        async with sem:
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                await proc.wait()
                return None, None
            return out, err
    except Exception:
        if proc:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                await proc.wait()
            except Exception:
                pass
        return None, None


# --- persistent ffmpeg (long-running) helpers using a threading.Semaphore ---
_persistent_semaphore: threading.Semaphore | None = None


def _get_persistent_semaphore() -> threading.Semaphore:
    global _persistent_semaphore
    if _persistent_semaphore is None:
        limit = max(1, int(getattr(config, 'rtmp_max_streams', 3)))
        _persistent_semaphore = threading.Semaphore(limit)
    return _persistent_semaphore


def start_persistent_ffmpeg(cmd: list[str], popen_kwargs: dict) -> subprocess.Popen:
    """Start a long-running ffmpeg process if a slot is available.

    Acquires a semaphore slot; caller must call `release_persistent_slot()` after
    the process exits or is terminated to free the slot.
    """
    sem = _get_persistent_semaphore()
    acquired = sem.acquire(blocking=False)
    if not acquired:
        raise RuntimeError("No available ffmpeg slots")
    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
        return proc
    except Exception:
        # release slot on failure to start
        sem.release()
        raise


def release_persistent_slot() -> None:
    try:
        _get_persistent_semaphore().release()
    except Exception:
        pass
