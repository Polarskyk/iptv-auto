import asyncio
import http.cookies
import json
try:
    import orjson as _orjson  # fast C JSON
except Exception:
    _orjson = None
from collections import OrderedDict
import re
import subprocess
from time import time
from urllib.parse import quote, urljoin

import m3u8
from aiohttp import ClientSession, TCPConnector
from utils.http import get_shared_session
from multidict import CIMultiDictProxy

import utils.constants as constants
from utils.config import config
from utils.i18n import t
from utils.requests.tools import headers as request_headers
from utils.tools import get_resolution_value
from utils.types import TestResult, ChannelTestResult, TestResultCacheData

http.cookies._is_legal_key = lambda _: True
cache: TestResultCacheData = OrderedDict()
speed_test_timeout = config.speed_test_timeout
speed_test_filter_host = config.speed_test_filter_host
open_filter_resolution = config.open_filter_resolution
min_resolution_value = config.min_resolution_value
max_resolution_value = config.max_resolution_value
open_supply = config.open_supply
open_filter_speed = config.open_filter_speed
min_speed_value = config.min_speed
resolution_speed_map = config.resolution_speed_map
m3u8_headers = ['application/x-mpegurl', 'application/vnd.apple.mpegurl', 'audio/mpegurl', 'audio/x-mpegurl']
default_ipv6_delay = 0.1
default_ipv6_resolution = "1920x1080"
default_ipv6_result = {
    'speed': float("inf"),
    'delay': default_ipv6_delay,
    'resolution': default_ipv6_resolution
}

_speed_test_semaphore: asyncio.Semaphore | None = None
_speed_cache_key_limit = max(100, int(getattr(config, "urls_limit", 10)) * 50)
_speed_cache_sample_limit = max(5, int(getattr(config, "speed_test_limit", 5)) * 4)

def _get_speed_semaphore() -> asyncio.Semaphore:
    global _speed_test_semaphore
    if _speed_test_semaphore is None:
        limit = max(1, int(getattr(config, 'speed_test_limit', 5)))
        _speed_test_semaphore = asyncio.Semaphore(limit)
    return _speed_test_semaphore


def _get_cached_result(key: str):
    """Get cached result and mark it as recently used."""
    if key not in cache:
        return None
    cache.move_to_end(key)
    return cache[key]


def _put_cached_result(key: str, result: dict) -> None:
    """Insert a cached result while keeping cache size bounded."""
    if not key:
        return

    current = cache.get(key)
    if current is None:
        cache[key] = [result]
    else:
        current.append(result)
        if len(current) > _speed_cache_sample_limit:
            del current[:-_speed_cache_sample_limit]
        cache.move_to_end(key)

    while len(cache) > _speed_cache_key_limit:
        cache.popitem(last=False)

min_measure_time = 1.0
stability_window = 4
stability_threshold = 0.12

# Precompile regexes used repeatedly
_re_video = re.compile(r"video:\s*([0-9]+(?:\.[0-9]+)?)\s*(KiB|MiB|kB|B|kb|KB)?", re.IGNORECASE)
_re_audio = re.compile(r"audio:\s*([0-9]+(?:\.[0-9]+)?)\s*(KiB|MiB|kB|B|kb|KB)?", re.IGNORECASE)
_re_time = re.compile(r"time=\s*([0-9:\.]+)")
_re_lsize = re.compile(r"Lsize=\s*([0-9]+(?:\.[0-9]+)?)\s*(KiB|kB|MiB|B|kb|KB)?", re.IGNORECASE)
_re_size = re.compile(r"size=\s*([0-9]+(?:\.[0-9]+)?)\s*(KiB|kB|MiB|B|kb|KB)?", re.IGNORECASE)
_re_bitrate = re.compile(r"bitrate=\s*([0-9\.]+)\s*k?bits/s", re.IGNORECASE)
_re_frame = re.compile(r"frame=(\d+)")
_re_resolution = re.compile(r"(\d{3,4}x\d{3,4})")


async def get_speed_with_download(url: str, headers: dict = None, session: ClientSession = None,
                                  timeout: int = speed_test_timeout) -> dict[str, float | None]:
    """
    Get the speed of the url with a total timeout
    """
    start_time = time()
    delay = -1
    total_size = 0
    min_bytes = 64 * 1024
    last_sample_time = start_time
    last_sample_size = 0

    if session is None:
        session = await get_shared_session()
        created_session = False
    else:
        created_session = False

    speed_samples: list[float] = []
    try:
        async with session.get(url, headers=headers, timeout=timeout) as response:
            if response.status != 200:
                raise Exception("Invalid response")
            delay = int(round((time() - start_time) * 1000))
            async for chunk in response.content.iter_any():
                if chunk:
                    total_size += len(chunk)
                    now = time()
                    elapsed = now - start_time
                    delta_t = now - last_sample_time
                    delta_b = total_size - last_sample_size
                    if delta_t > 0 and delta_b > 0:
                        inst_speed = delta_b / delta_t / 1024.0 / 1024.0
                        speed_samples.append(inst_speed)
                        last_sample_time = now
                        last_sample_size = total_size
                    if (elapsed >= min_measure_time and total_size >= min_bytes
                            and len(speed_samples) >= stability_window):
                        window = speed_samples[-stability_window:]
                        mean = sum(window) / len(window)
                        if mean > 0 and (max(window) - min(window)) / mean < stability_threshold:
                            total_time = elapsed
                            return {
                                'speed': total_size / total_time / 1024 / 1024,
                                'delay': delay,
                                'size': total_size,
                                'time': total_time,
                            }
    except:
        pass
    finally:
        total_time = time() - start_time
        if created_session:
            await session.close()
        speed_value = total_size / total_time / 1024 / 1024 if total_time > 0 else 0.0
        return {
            'speed': speed_value,
            'delay': delay,
            'size': total_size,
            'time': total_time,
        }


async def get_headers(url: str, headers: dict = None, session: ClientSession = None, timeout: int = 5) -> \
        CIMultiDictProxy[str] | dict[
            any, any]:
    """
    Get the headers of the url
    """
    if session is None:
        session = await get_shared_session()
        created_session = False
    else:
        created_session = False
    res_headers = {}
    try:
        async with session.head(url, headers=headers, timeout=timeout) as response:
            res_headers = response.headers
    except:
        pass
    finally:
        if created_session:
            await session.close()
        return res_headers


async def get_url_content(url: str, headers: dict = None, session: ClientSession = None,
                          timeout: int = speed_test_timeout) -> str:
    """
    Get the content of the url
    """
    if session is None:
        session = await get_shared_session()
        created_session = False
    else:
        created_session = False
    content = ""
    try:
        async with session.get(url, headers=headers, timeout=timeout) as response:
            if response.status == 200:
                content = await response.text()
            else:
                raise Exception("Invalid response")
    except:
        pass
    finally:
        if created_session:
            await session.close()
        return content


def check_m3u8_valid(headers: CIMultiDictProxy[str] | dict[any, any]) -> bool:
    """
    Check if the m3u8 url is valid
    """
    content_type = headers.get('Content-Type', '').lower()
    if not content_type:
        return False
    return any(item in content_type for item in m3u8_headers)


def _parse_time_to_seconds(t: str) -> float:
    """
    Parse time string to seconds
    """
    if not t:
        return 0.0
    parts = [p.strip() for p in t.split(':') if p.strip() != ""]
    if not parts:
        return 0.0
    try:
        total = 0.0
        for i, part in enumerate(reversed(parts)):
            total += float(part) * (60 ** i)
        return total
    except Exception:
        return 0.0


def _try_extract_speed_from_ffmpeg_output(output: str) -> float | None:
    """
    Try to extract speed from ffmpeg output
    """

    def parse_size_value(value_str: str, unit: str | None) -> float:
        try:
            val = float(value_str)
        except Exception:
            return 0.0
        if not unit:
            return val
        unit_lower = unit.lower()
        if unit_lower in ("b", "bytes"):
            return val
        if unit_lower in ("kib", "k"):
            return val * 1024.0
        if unit_lower in ("kb",):
            return val * 1000.0
        if unit_lower in ("mib", "mb"):
            return val * 1024.0 * 1024.0
        return val

    try:
        total_bytes = 0.0
        m_video = _re_video.search(output)
        m_audio = _re_audio.search(output)
        if m_video:
            total_bytes += parse_size_value(m_video.group(1), m_video.group(2))
        if m_audio:
            total_bytes += parse_size_value(m_audio.group(1), m_audio.group(2))

        m_time = _re_time.search(output)
        if total_bytes > 0 and m_time:
            secs = _parse_time_to_seconds(m_time.group(1))
            if secs > 0:
                return total_bytes / secs / 1024.0 / 1024.0
    except Exception:
        pass

    try:
        m_lsize = _re_lsize.search(output)
        m_size = _re_size.search(output)
        m_time = _re_time.search(output)
        size_bytes = 0.0
        if m_lsize and m_lsize.group(1).upper() != "N/A":
            size_bytes = parse_size_value(m_lsize.group(1), m_lsize.group(2))
        elif m_size:
            size_bytes = parse_size_value(m_size.group(1), m_size.group(2))
        if size_bytes > 0 and m_time:
            secs = _parse_time_to_seconds(m_time.group(1))
            if secs > 0:
                return size_bytes / secs / 1024.0 / 1024.0
    except Exception:
        pass

    try:
        m_bitrate = _re_bitrate.search(output)
        if m_bitrate:
            kbps = float(m_bitrate.group(1))
            return kbps / 8.0 / 1024.0
    except Exception:
        pass

    return None


async def get_result(url: str, headers: dict = None, resolution: str = None,
                     filter_resolution: bool = config.open_filter_resolution,
                     timeout: int = speed_test_timeout) -> dict[str, float | None]:
    """
    Get the test result of the url
    """
    info = {'speed': 0, 'delay': -1, 'resolution': resolution}
    location = None
    try:
        url = quote(url, safe=':/?$&=@[]%').partition('$')[0]
        session = await get_shared_session()
            res_headers = await get_headers(url, headers, session)
            location = res_headers.get('Location')
            if location:
                info.update(await get_result(location, headers, resolution, filter_resolution, timeout))
            else:
                url_content = await get_url_content(url, headers, session, timeout)
                if url_content:
                    m3u8_obj = m3u8.loads(url_content)
                    playlists = m3u8_obj.playlists
                    segments = m3u8_obj.segments
                    if playlists:
                        best_playlist = max(m3u8_obj.playlists, key=lambda p: p.stream_info.bandwidth)
                        playlist_url = urljoin(url, best_playlist.uri)
                        playlist_content = await get_url_content(playlist_url, headers, session, timeout)
                        if playlist_content:
                            media_playlist = m3u8.loads(playlist_content)
                            segment_urls = [urljoin(playlist_url, segment.uri) for segment in media_playlist.segments]
                    else:
                        segment_urls = [urljoin(url, segment.uri) for segment in segments]
                    if not segment_urls:
                        raise Exception("Segment urls not found")
                else:
                    res_info = await get_speed_with_download(url, headers, session, timeout)
                    info.update({'speed': res_info['speed'], 'delay': res_info['delay']})
                start_time = time()
                sem = _get_speed_semaphore()
                async def _seg_task(u):
                    async with sem:
                        return await get_speed_with_download(u, headers, session, timeout)

                tasks = [_seg_task(ts_url) for ts_url in segment_urls[:5]]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                total_size = sum(result['size'] for result in results if isinstance(result, dict))
                total_time = sum(result['time'] for result in results if isinstance(result, dict))
                info['speed'] = total_size / total_time / 1024 / 1024 if total_time > 0 else 0
                info['delay'] = int(round((time() - start_time) * 1000))
                try:
                    if round(info['speed'], 2) == 0 and info['delay'] != -1:
                        ff_out = await ffmpeg_url(url, headers, timeout)
                        if ff_out:
                            parsed_speed = _try_extract_speed_from_ffmpeg_output(ff_out)
                            if parsed_speed is not None and parsed_speed > 0:
                                info['speed'] = parsed_speed
                            try:
                                _, parsed_resolution = get_video_info(ff_out)
                                if parsed_resolution:
                                    info['resolution'] = parsed_resolution
                            except Exception:
                                pass
                except Exception:
                    pass
    except:
        pass
    finally:
        if not info['resolution'] and filter_resolution and not location and info['delay'] != -1:
            info['resolution'] = await get_resolution_ffprobe(url, headers, timeout)
        return info


async def get_delay_requests(url, timeout=speed_test_timeout, proxy=None):
    """
    Get the delay of the url by requests
    """
    session = await get_shared_session()
        start = time()
        end = None
        try:
            async with session.get(url, timeout=timeout, proxy=proxy) as response:
                if response.status == 404:
                    return -1
                content = await response.read()
                if content:
                    end = time()
                else:
                    return -1
        except Exception as e:
            return -1
        return int(round((end - start) * 1000)) if end else -1


def check_ffmpeg_installed_status():
    """
    Check ffmpeg is installed
    """
    # Use shutil.which to avoid spawning a process just to check presence
    try:
        import shutil
        return shutil.which("ffmpeg") is not None
    except Exception:
        return False
    except Exception as e:
        print(e)
    finally:
        if status:
            print(t("msg.ffmpeg_installed"))
        else:
            print(t("msg.ffmpeg_not_installed"))
        return status


from utils.ffmpeg_pool import run_ffmpeg


async def ffmpeg_url(url, headers=None, timeout=speed_test_timeout):
    """
    Get the ffmpeg output of the url
    """
    headers_str = "".join(f"{k}: {v}\r\n" for k, v in headers.items())

    args = ["ffmpeg", "-t", str(timeout)]
    if headers_str:
        args += ["-headers", headers_str]
    args += ["-http_persistent", "0", "-stats", "-i", url, "-f", "null", "-"]

    proc = None
    stderr_parts: list[bytes] = []
    speed_samples: list[float] = []
    bitrate_re = _re_bitrate
    start = time()

    # Use centralized ffmpeg pool to run subprocess and collect output
    out, err = await run_ffmpeg(args, timeout)
    if out is None and err is None:
        return None
    stderr_bytes = b"".join((err or b"", out or b""))
    try:
        return stderr_bytes.decode(errors="ignore")
    except Exception:
        return None


async def get_resolution_ffprobe(url: str, headers: dict = None, timeout: int = speed_test_timeout) -> str | None:
    """
    Get the resolution of the url by ffprobe
    """
    resolution = None
    proc = None
    sem = _get_speed_semaphore()
    try:
        probe_args = [
            'ffprobe',
            '-v', 'error',
            '-headers', ''.join(f'{k}: {v}\r\n' for k, v in headers.items()) if headers else '',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            "-of", 'json',
            url
        ]
        out, err = await run_ffmpeg(probe_args, timeout)
        if out:
            try:
                if _orjson:
                    video_stream = _orjson.loads(out)["streams"][0]
                else:
                    video_stream = json.loads(out.decode('utf-8'))["streams"][0]
            except Exception:
                video_stream = None
            resolution = f"{video_stream['width']}x{video_stream['height']}"
    except Exception:
        if proc:
            proc.kill()
    finally:
        if proc:
            await proc.wait()
        return resolution


def get_video_info(video_info):
    """
    Get the video info
    """
    frame_size = -1
    resolution = None
    if video_info is not None:
        info_data = video_info.replace(" ", "")
        matches = _re_frame.findall(info_data)
        if matches:
            frame_size = int(matches[-1])
        match = _re_resolution.search(video_info)
        if match:
            resolution = match.group(0)
    return frame_size, resolution


async def check_stream_delay(url_info):
    """
    Check the stream delay
    """
    try:
        url = url_info["url"]
        video_info = await ffmpeg_url(url)
        if video_info is None:
            return -1
        frame, resolution = get_video_info(video_info)
        if frame is None or frame == -1:
            return -1
        url_info["resolution"] = resolution
        return url_info, frame
    except Exception as e:
        print(e)
        return -1


def get_avg_result(result) -> TestResult:
    return {
        'speed': sum(item['speed'] or 0 for item in result) / len(result),
        'delay': max(
            int(sum(item['delay'] or -1 for item in result) / len(result)), -1),
        'resolution': max((item['resolution'] for item in result), key=get_resolution_value)
    }


def get_speed_result(key: str) -> TestResult:
    """
    Get the speed result of the url
    """
    cached = _get_cached_result(key)
    if cached:
        return get_avg_result(cached)
    else:
        return {'speed': 0, 'delay': -1, 'resolution': 0}


async def get_speed(data, headers=None, ipv6_proxy=None, filter_resolution=open_filter_resolution,
                    timeout=speed_test_timeout, logger=None, callback=None) -> TestResult:
    """
    Get the speed (response time and resolution) of the url
    """
    url = data['url']
    resolution = data['resolution']
    result: TestResult = {'speed': 0, 'delay': -1, 'resolution': resolution}
    headers = {**request_headers, **(headers or {})}
    try:
        cache_key = data['host'] if speed_test_filter_host else url
        cached = _get_cached_result(cache_key) if cache_key else None
        if cached:
            result = get_avg_result(cached)
        else:
            if data['ipv_type'] == "ipv6" and ipv6_proxy:
                result.update(default_ipv6_result)
            elif constants.rt_url_pattern.match(url) is not None:
                start_time = time()
                if not result['resolution'] and filter_resolution:
                    result['resolution'] = await get_resolution_ffprobe(url, headers, timeout)
                result['delay'] = int(round((time() - start_time) * 1000))
                if result['resolution'] is not None:
                    result['speed'] = float("inf")
            else:
                result.update(await get_result(url, headers, resolution, filter_resolution, timeout))
            if cache_key:
                _put_cached_result(cache_key, result)
    finally:
        if callback:
            callback()
        if logger:
            origin = data.get('origin')
            origin_name = t(f"name.{origin}") if origin else origin
            logger.info(
                f"{t("name.name")}: {data.get('name')}, {t("pbar.url")}: {data.get('url')}, {t("name.from")}: {origin_name}, {t("name.ipv_type")}: {data.get("ipv_type")}, {t("name.location")}: {data.get('location')}, {t("name.isp")}: {data.get('isp')}, {t("name.date")}: {data["date"]}, {t("name.delay")}: {result.get('delay') or -1} ms, {t("name.speed")}: {result.get('speed') or 0:.2f} M/s, {t("name.resolution")}: {result.get('resolution')}"
            )
        return result


def get_sort_result(
        results,
        supply=open_supply,
        filter_speed=open_filter_speed,
        min_speed=min_speed_value,
        filter_resolution=open_filter_resolution,
        min_resolution=min_resolution_value,
        max_resolution=max_resolution_value,
        ipv6_support=True
) -> list[ChannelTestResult]:
    """
    get the sort result
    """
    total_result = []
    for result in results:
        if not ipv6_support and result["ipv_type"] == "ipv6":
            result.update(default_ipv6_result)
        result_speed, result_delay, resolution = (
            result.get("speed") or 0,
            result.get("delay"),
            result.get("resolution")
        )
        if result_delay == -1:
            continue
        if not supply:
            if filter_speed and result_speed < resolution_speed_map.get(resolution, min_speed):
                continue
            if filter_resolution and resolution:
                resolution_value = get_resolution_value(resolution)
                if resolution_value < min_resolution or resolution_value > max_resolution:
                    continue
        total_result.append(result)
    total_result.sort(key=lambda item: item.get("speed") or 0, reverse=True)
    return total_result


def clear_cache():
    """
    Clear the speed test cache
    """
    global cache
    cache = OrderedDict()
