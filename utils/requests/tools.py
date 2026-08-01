import re
import threading
import os
import concurrent.futures

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from utils.config import config

headers = {
    "Accept": "*/*",
    "Connection": "keep-alive",
    "Accept-Language": "zh-CN,zh;q=0.8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
}

# Thread-local session to avoid creating a new Session for every call
_local = threading.local()

# executor for offloading HTML parsing (limits concurrent CPU-bound BeautifulSoup parses)
_parse_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=min(8, max(2, (os.cpu_count() or 1) * 2))
)

def _create_session():
    s = requests.Session()
    # configure a connection pool and some retries
    retries = Retry(total=2, backoff_factor=0.1, status_forcelist=[502, 503, 504])
    adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retries)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

def _get_session():
    sess = getattr(_local, 'session', None)
    if sess is None:
        sess = _create_session()
        _local.session = sess
    return sess


def get_requests(url, data=None, proxy=None, timeout=30):
    """
    Get the response by requests
    """
    if proxy is None:
        proxy = config.http_proxy
    proxies = {"http": proxy, "https": proxy} if proxy else None
    response = None
    try:
        session = _get_session()
        if data:
            response = session.post(
                url, headers=headers, data=data, proxies=proxies, timeout=timeout
            )
        else:
            response = session.get(url, headers=headers, proxies=proxies, timeout=timeout)
    except requests.RequestException as e:
        raise e

    if response is None:
        raise requests.RequestException(f"No response from {url}")

    text = re.sub(r"<!--.*?-->", "", response.text or "", flags=re.DOTALL)
    if not text.strip():
        raise requests.RequestException(f"Empty response from {url}")

    return response


def get_soup_requests(url, data=None, proxy=None, timeout=30):
    """
    Get the soup by requests
    """
    response = get_requests(url, data, proxy, timeout)
    source = re.sub(r"<!--.*?-->", "", response.text or "", flags=re.DOTALL)
    # offload parsing to threadpool to limit concurrent CPU-bound work
    future = _parse_executor.submit(BeautifulSoup, source, "html.parser")
    return future.result()
