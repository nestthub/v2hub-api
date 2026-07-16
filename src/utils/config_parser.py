"""
Proxy configuration parsing and validation utilities.

Provides functions for:
- Parsing proxy URIs (vless, vmess, trojan, ss, etc.)
- Extracting config hash without fragment
- Validating proxy configurations
- Detecting protocol types
"""

import base64
import hashlib
from typing import Optional, Tuple
from urllib.parse import urlparse, unquote

from src.core.enums import ProxyProtocol
from src.core.config import settings


# ═══════════════════════════════════════════════════════════════════════════
# Protocol Detection
# ═══════════════════════════════════════════════════════════════════════════

def detect_protocol(uri: str) -> Optional[ProxyProtocol]:
    """
    Detect proxy protocol from URI.
    
    Args:
        uri: Proxy configuration URI
        
    Returns:
        ProxyProtocol enum or None if not recognized
    """
    if not uri or "://" not in uri:
        return None
    
    return ProxyProtocol.from_uri(uri)


def is_valid_proxy_uri(uri: str) -> bool:
    """
    Check if URI is a valid proxy configuration.
    
    Args:
        uri: URI to validate
        
    Returns:
        True if valid proxy URI
    """
    protocol = detect_protocol(uri)
    return protocol is not None


# ═══════════════════════════════════════════════════════════════════════════
# Config Parsing
# ═══════════════════════════════════════════════════════════════════════════

def split_config_and_comment(config: str) -> Tuple[str, Optional[str]]:
    """
    Split proxy config into base config and comment.
    
    Args:
        config: Full config URI (may include #comment)
        
    Returns:
        Tuple of (config_without_fragment, comment)
        
    Example:
        "vless://uuid@host:port?params#MyServer" 
        -> ("vless://uuid@host:port?params", "MyServer")
    """
    config = config.strip()
    
    if "#" in config:
        base_config, comment = config.split("#", 1)
        return base_config.strip(), comment.strip()
    
    return config, None


def normalize_config(config: str) -> str:
    """
    Normalize config by removing fragment and whitespace.
    
    Args:
        config: Proxy configuration URI
        
    Returns:
        Normalized config without fragment
    """
    base_config, _ = split_config_and_comment(config)
    return base_config


def get_config_hash(config: str) -> str:
    """
    Generate stable hash for proxy config.
    
    Uses blake2b with 16-byte digest for deduplication.
    Strips fragment (#comment) before hashing.
    
    Args:
        config: Proxy configuration URI
        
    Returns:
        Hex-encoded hash (32 characters)
    """
    normalized = normalize_config(config)
    return hashlib.blake2b(
        normalized.encode('utf-8'),
        digest_size=16
    ).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════
# URL Utilities
# ═══════════════════════════════════════════════════════════════════════════

def is_http_url(text: str) -> bool:
    """
    Check if text is a valid HTTP/HTTPS URL.
    
    Args:
        text: String to check
        
    Returns:
        True if valid HTTP(S) URL
    """
    try:
        parsed = urlparse(text.strip())
        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.netloc)
            and bool(parsed.hostname)
        )
    except Exception:
        return False


def get_url_hash(url: str) -> str:
    """
    Generate stable hash for URL.
    
    Args:
        url: URL to hash
        
    Returns:
        Hex-encoded hash (32 characters)
    """
    normalized = url.strip()
    return hashlib.blake2b(
        normalized.encode('utf-8'),
        digest_size=16
    ).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════
# Base64 Decoding
# ═══════════════════════════════════════════════════════════════════════════

def decode_base64_subscription(content: str) -> str:
    """
    Decode base64-encoded subscription content.
    
    Handles:
    - Standard base64 padding
    - URL-safe base64
    - Already decoded content
    
    Args:
        content: Raw subscription content
        
    Returns:
        Decoded content (or original if not base64)
    """
    content = content.strip()
    
    # Already looks like plain text
    if "://" in content or "\n" in content:
        return content
    
    # Try to decode as base64
    try:
        # Remove whitespace
        compact = "".join(content.split())
        
        # Add padding if needed
        padding = (4 - len(compact) % 4) % 4
        padded = compact + "=" * padding
        
        # Decode
        decoded_bytes = base64.b64decode(padded, validate=True)
        decoded = decoded_bytes.decode('utf-8')
        
        # Only accept if it looks like subscription content
        if any(proto.value + "://" in decoded for proto in ProxyProtocol):
            return decoded
        
    except Exception:
        pass
    
    return content


# ═══════════════════════════════════════════════════════════════════════════
# Config List Parsing
# ═══════════════════════════════════════════════════════════════════════════

def parse_subscription_content(content: str) -> list[str]:
    """
    Parse subscription content into list of proxy configs.
    
    Handles:
    - Base64-encoded content
    - Newline-separated configs
    - Comment lines (starting with #)
    - Blank lines
    
    Args:
        content: Raw subscription content
        
    Returns:
        List of valid proxy configuration URIs
    """
    # Decode if base64
    content = decode_base64_subscription(content)
    
    configs = []
    for line in content.splitlines():
        line = line.strip()
        
        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue
        
        # Only include valid proxy URIs
        if is_valid_proxy_uri(line):
            configs.append(line)
    
    return configs


# ═══════════════════════════════════════════════════════════════════════════
# Deduplication
# ═══════════════════════════════════════════════════════════════════════════

def deduplicate_configs(configs: list[str]) -> list[str]:
    """
    Remove duplicate configs while preserving order.
    
    Deduplication is based on config hash (without fragment),
    so configs with different comments are treated as the same.
    
    Args:
        configs: List of proxy configs
        
    Returns:
        Deduplicated list preserving original order
    """
    seen_hashes = set()
    unique_configs = []
    
    for config in configs:
        config_hash = get_config_hash(config)
        if config_hash not in seen_hashes:
            seen_hashes.add(config_hash)
            unique_configs.append(config)
    
    return unique_configs


# ═══════════════════════════════════════════════════════════════════════════
# Config Validation
# ═══════════════════════════════════════════════════════════════════════════

def validate_vless_config(uri: str) -> Tuple[bool, Optional[str]]:
    """
    Validate VLESS configuration.
    
    Returns:
        (is_valid, error_message)
    """
    try:
        parsed = urlparse(uri)
        if parsed.scheme != "vless":
            return False, "Invalid scheme"
        
        if not parsed.netloc:
            return False, "Missing server address"
        
        # UUID should be in the username part
        uuid = parsed.username
        if not uuid or len(uuid) != 36:
            return False, "Invalid UUID"
        
        return True, None
        
    except Exception as e:
        return False, str(e)


def validate_vmess_config(uri: str) -> Tuple[bool, Optional[str]]:
    """
    Validate VMess configuration.
    
    VMess can be either URI format or base64 JSON.
    """
    try:
        if uri.startswith("vmess://"):
            # URI format
            parsed = urlparse(uri)
            if not parsed.netloc:
                return False, "Missing server address"
            return True, None
        
        return False, "Invalid VMess format"
        
    except Exception as e:
        return False, str(e)


def validate_trojan_config(uri: str) -> Tuple[bool, Optional[str]]:
    """Validate Trojan configuration."""
    try:
        parsed = urlparse(uri)
        if parsed.scheme != "trojan":
            return False, "Invalid scheme"
        
        if not parsed.netloc:
            return False, "Missing server address"
        
        # Password is in username
        if not parsed.username:
            return False, "Missing password"
        
        return True, None
        
    except Exception as e:
        return False, str(e)


def validate_shadowsocks_config(uri: str) -> Tuple[bool, Optional[str]]:
    """Validate Shadowsocks configuration."""
    try:
        parsed = urlparse(uri)
        if parsed.scheme not in ("ss", "shadowsocks"):
            return False, "Invalid scheme"
        
        if not parsed.netloc:
            return False, "Missing server address"
        
        return True, None
        
    except Exception as e:
        return False, str(e)


def validate_proxy_config(config: str) -> Tuple[bool, Optional[str]]:
    """
    Validate proxy configuration based on protocol.
    
    Args:
        config: Proxy configuration URI
        
    Returns:
        (is_valid, error_message)
    """
    protocol = detect_protocol(config)
    
    if not protocol:
        return False, "Unknown or invalid protocol"
    
    validators = {
        ProxyProtocol.VLESS: validate_vless_config,
        ProxyProtocol.VMESS: validate_vmess_config,
        ProxyProtocol.TROJAN: validate_trojan_config,
        ProxyProtocol.SHADOWSOCKS: validate_shadowsocks_config,
    }
    
    validator = validators.get(protocol)
    if validator:
        return validator(config)
    
    # For protocols without specific validator, just check format
    return True, None

# ─────────────────────────────────────────────────────────
# Utils
# ─────────────────────────────────────────────────────────

def _clean_sources(items: list[str]) -> list[str]:
    cleaned, seen = [], set()
    for item in items:
        v = item.strip()
        if v and v not in seen:
            seen.add(v)
            cleaned.append(v)
    return cleaned


def normalize_source(source: str, max_comment_length: int | None = None) -> str:
    """
    Приводит source к валидному виду:
    - декодирует comment (#...)
    - убирает двойное/тройное encoding
    - валидирует длину comment
    """

    # 1. разделяем url и comment
    if "#" in source:
        url, comment = source.split("#", 1)

        # 2. многократный decode (фикс %25%25...)
        prev = None
        while prev != comment:
            prev = comment
            comment = unquote(comment)

        comment = comment.strip()

        # 3. проверка длины
        if max_comment_length is not None and len(comment) > max_comment_length:
            raise ValueError(
                f"comment too long (max {max_comment_length})"
            )

        # 4. безопасное восстановление
        return f"{url}#{comment}"

    return source

def _normalize_sources(values):
    cleaned = []
    seen = set()

    for item in values:
        if isinstance(item, str):
            key = item.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            cleaned.append({
                "data": normalize_source(key, settings.max_comment_length),
            })
        elif isinstance(item, dict):
            key = (item.get("data") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            item = item.copy()
            item["data"] = normalize_source(key, settings.max_comment_length)
            cleaned.append(item)
        else:
            raise TypeError("Each source must be either a string or an object")

    return cleaned
