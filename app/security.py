"""SSRF protection and URL validation — pure functions, no side effects."""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse, urlunparse

from app.config import settings

logger = logging.getLogger(__name__)

# Private / reserved CIDR blocks to reject
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fd00::/8"),
    ipaddress.ip_network("fe80::/10"),
]

_BLOCKED_HOSTNAMES = {"metadata.google.internal"}

_ALLOWED_SCHEMES = {"http", "https"}

MAX_URL_LENGTH = 8192


def validate_url(url: str) -> str:
    """Validate and normalize a URL. Return the cleaned URL or raise ValueError."""
    if not isinstance(url, str):
        raise ValueError("URL must be a string")

    url = url.strip()
    if not url:
        raise ValueError("URL must not be empty")

    if len(url) > MAX_URL_LENGTH:
        raise ValueError(f"URL exceeds maximum length of {MAX_URL_LENGTH} characters")

    parsed = urlparse(url)

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValueError(f"Scheme '{parsed.scheme}' is not allowed — only http and https")

    if not parsed.hostname:
        raise ValueError("URL has no hostname")

    if parsed.username or parsed.password:
        raise ValueError("URLs with credentials (user:pass@host) are not allowed")

    # Strip fragment
    cleaned = urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path or "/",
        parsed.params,
        parsed.query,
        "",  # no fragment
    ))

    return cleaned


def resolve_and_check_host(hostname: str) -> list[str]:
    """Resolve hostname to IP addresses and check each against blocked ranges.

    Returns the list of resolved IP strings. Raises ValueError if any IP is blocked.
    """
    hostname_lower = hostname.lower()

    if hostname_lower in _BLOCKED_HOSTNAMES:
        raise ValueError(f"Hostname '{hostname}' is blocked (cloud metadata endpoint)")

    try:
        addr_infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed for '{hostname}': {exc}") from exc

    if not addr_infos:
        raise ValueError(f"No DNS records for '{hostname}'")

    resolved_ips: list[str] = []
    for family, _type, _proto, _canonname, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        ip_addr = ipaddress.ip_address(ip_str)

        for net in _BLOCKED_NETWORKS:
            if ip_addr in net:
                raise ValueError(
                    f"Resolved IP {ip_str} for '{hostname}' is in blocked range {net}"
                )

        # Specific IP check for cloud metadata
        if ip_str in ("169.254.169.254",):
            raise ValueError(f"Resolved IP {ip_str} is a cloud metadata endpoint")

        resolved_ips.append(ip_str)

    return resolved_ips


def check_url_ssrf(url: str) -> str:
    """Full SSRF validation: validate URL format, resolve DNS, check IPs.

    Returns the validated URL. Raises ValueError on any violation.
    """
    validated_url = validate_url(url)
    parsed = urlparse(validated_url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")

    resolve_and_check_host(hostname)
    return validated_url


def check_redirect_url(url: str) -> str:
    """Validate a redirect target URL (same checks as initial URL)."""
    return check_url_ssrf(url)
