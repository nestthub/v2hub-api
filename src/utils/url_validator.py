"""
URL validation utilities for security.

Validates URLs to prevent SSRF attacks by blocking:
- Local IP addresses (127.x.x.x, localhost)
- Private network ranges (10.x.x.x, 172.16-31.x.x, 192.168.x.x)
- Link-local addresses (169.254.x.x)
- Special use addresses
"""

import ipaddress
import re
from typing import Optional
from urllib.parse import urlparse

from src.core.exceptions import InvalidURLError


# Regex patterns for quick hostname validation
LOCALHOST_PATTERN = re.compile(r'^(localhost|127\.\d+\.\d+\.\d+)$', re.IGNORECASE)
PRIVATE_IP_PATTERN = re.compile(
    r'^(10\.\d+\.\d+\.\d+|'
    r'172\.(1[6-9]|2[0-9]|3[0-1])\.\d+\.\d+|'
    r'192\.168\.\d+\.\d+|'
    r'169\.254\.\d+\.\d+|'
    r'0\.0\.0\.0|'
    r'255\.255\.255\.255)$'
)


def is_private_ip(ip_str: str) -> bool:
    """
    Check if IP address is private/local.
    
    Args:
        ip_str: IP address string
        
    Returns:
        True if IP is private/local
    """
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private or
            ip.is_loopback or
            ip.is_link_local or
            ip.is_reserved or
            ip.is_multicast
        )
    except ValueError:
        return False


def validate_external_url(url: str) -> None:
    """
    Validate that URL is safe for external fetching.
    
    Blocks:
    - localhost and 127.x.x.x
    - Private IP ranges (10.x, 192.168.x, 172.16-31.x)
    - Link-local addresses (169.254.x.x)
    - Non-HTTP(S) schemes
    
    Args:
        url: URL to validate
        
    Raises:
        InvalidURLError: If URL is not safe
    """
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise InvalidURLError(f"Invalid URL format: {e}")
    
    # Check scheme
    if parsed.scheme not in ('http', 'https'):
        raise InvalidURLError(
            f"Invalid URL scheme: {parsed.scheme}. Only http/https allowed"
        )
    
    # Check hostname exists
    hostname = parsed.hostname
    if not hostname:
        raise InvalidURLError("URL must have a hostname")
    
    # Quick check for localhost
    if LOCALHOST_PATTERN.match(hostname):
        raise InvalidURLError(
            "Localhost and 127.x.x.x addresses are not allowed"
        )
    
    # Quick check for private IPs using regex
    if PRIVATE_IP_PATTERN.match(hostname):
        raise InvalidURLError(
            "Private IP addresses are not allowed (10.x, 192.168.x, 172.16-31.x, 169.254.x)"
        )
    
    # If it looks like an IP, do a thorough check
    if re.match(r'^\d+\.\d+\.\d+\.\d+$', hostname):
        if is_private_ip(hostname):
            raise InvalidURLError(
                f"IP address {hostname} is private/local and not allowed"
            )
    
    # Check for IPv6 localhost
    if hostname.lower() in ('::1', '::ffff:127.0.0.1'):
        raise InvalidURLError("IPv6 localhost is not allowed")
    
    # Additional checks for common bypass attempts
    if hostname.lower() in (
        '0.0.0.0',
        '0000.0000.0000.0000',
        'broadcasthost',
    ):
        raise InvalidURLError(f"Hostname {hostname} is not allowed")


def is_url_safe(url: str) -> bool:
    """
    Check if URL is safe without raising exception.
    
    Args:
        url: URL to check
        
    Returns:
        True if URL is safe, False otherwise
    """
    try:
        validate_external_url(url)
        return True
    except Exception:
        return False


def extract_hostname(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)

        if parsed.hostname:
            return parsed.hostname.lower()

        # fallback: если нет схемы (example.com/...)
        parsed = urlparse(f"//{url}")
        return parsed.hostname.lower() if parsed.hostname else None

    except Exception:
        return None


def is_internal(source: str, domain: str) -> bool:
    src_host = extract_hostname(source)
    domain_host = extract_hostname(domain)

    return src_host == domain_host
