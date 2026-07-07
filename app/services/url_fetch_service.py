import ipaddress
import socket
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import HTTPException, status

MAX_REDIRECTS = 5
MAX_BYTES = 2_000_000  # 2MB cap on the raw response body
FETCH_TIMEOUT = 8
USER_AGENT = "Mozilla/5.0 (compatible; JobTrackerBot/1.0; +https://github.com/)"


def _is_blocked_host(hostname: str) -> bool:
    """Resolves the hostname and rejects anything pointing at a private/internal network
    (loopback, link-local incl. cloud metadata 169.254.169.254, RFC1918, etc.) — this is the
    core SSRF guard for a server that fetches user-supplied URLs."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return True

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return True
    return False


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only http/https URLs are supported")
    if not parsed.hostname:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid URL")
    if _is_blocked_host(parsed.hostname):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This URL cannot be fetched")


def _fetch_raw_html(url: str) -> str:
    """Fetches a URL, manually validating + re-checking every redirect hop against the SSRF
    guard (requests' built-in redirect following would skip that check on each hop)."""
    current = url
    for _ in range(MAX_REDIRECTS):
        _validate_url(current)
        try:
            resp = requests.get(
                current, headers={"User-Agent": USER_AGENT},
                timeout=FETCH_TIMEOUT, allow_redirects=False, stream=True,
            )
        except requests.RequestException as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Could not fetch URL: {e}")

        if resp.is_redirect or resp.is_permanent_redirect:
            location = resp.headers.get("Location")
            if not location:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Redirect with no location")
            current = requests.compat.urljoin(current, location)
            continue

        if resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"URL returned status {resp.status_code}"
            )

        content = b""
        for chunk in resp.iter_content(chunk_size=8192):
            content += chunk
            if len(content) > MAX_BYTES:
                break
        return content.decode(resp.encoding or "utf-8", errors="ignore")

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Too many redirects")


def fetch_job_posting_text(url: str) -> str:
    """Fetches a job posting URL and returns cleaned, AI-ready plain text."""
    html = _fetch_raw_html(url)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)[:6000]
