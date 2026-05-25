"""
Hardened HTTP client for fetching external subscription URLs.

Features:
- HTTP/HTTPS only
- Blocks IP-literal targets in production
- Blocks localhost / private / link-local / reserved / metadata targets
- DNS rebinding detection
- Response size limit
- Timeout handling
- Custom aiohttp resolver to reduce TOCTOU SSRF risk
- Content-Type validation
- Malicious content detection
- Executable content blocking
- Encoding validation
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from typing import Optional

import aiohttp
from aiohttp.abc import AbstractResolver
from urllib.parse import urlparse

from src.core.config import settings
from src.core.exceptions import ExternalFetchError

logger = logging.getLogger(__name__)

# Common metadata endpoints / internal names.
_BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
}

# Common cloud metadata IPs.
_BLOCKED_METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),  # AWS / generic metadata
    ipaddress.ip_address("fd00:ec2::254"),     # AWS IPv6 metadata
}

# Allowed Content-Type для подписок (только текст)
_ALLOWED_CONTENT_TYPES = {
    "text/plain",
    "text/html",
    "application/octet-stream",  # Многие сервисы отдают подписки как binary
    "application/x-www-form-urlencoded",
}

# Executable file signatures (magic bytes)
_EXECUTABLE_SIGNATURES = [
    b"MZ",              # PE executable (Windows .exe/.dll)
    b"\x7fELF",         # ELF executable (Linux)
    b"\xca\xfe\xba\xbe",  # Mach-O (macOS)
    b"\xfe\xed\xfa",    # Mach-O 64-bit
    b"#!/",             # Shell script
    b"<?php",           # PHP script
    b"<script",         # HTML script tag
    b"javascript:",     # JavaScript URI
    b"vbscript:",       # VBScript URI
]

# Подозрительные паттерны в контенте
_MALICIOUS_PATTERNS = [
    re.compile(rb"<script[^>]*>", re.IGNORECASE),  # JavaScript
    re.compile(rb"javascript:", re.IGNORECASE),
    re.compile(rb"vbscript:", re.IGNORECASE),
    re.compile(rb"on\w+\s*=", re.IGNORECASE),  # HTML event handlers
    re.compile(rb"<iframe", re.IGNORECASE),
    re.compile(rb"eval\s*\(", re.IGNORECASE),
    re.compile(rb"exec\s*\(", re.IGNORECASE),
    re.compile(rb"system\s*\(", re.IGNORECASE),
    re.compile(rb"__import__", re.IGNORECASE),
    # SQL injection patterns
    re.compile(rb"union\s+select", re.IGNORECASE),
    re.compile(rb"drop\s+table", re.IGNORECASE),
    # Command injection
    re.compile(rb";\s*(rm|del|format|mkfs)", re.IGNORECASE),
]

# Максимальное количество строк (защита от billion laughs attack)
_MAX_LINES = 50000


class _GuardedResolver(AbstractResolver):
    """
    Custom resolver that validates DNS answers before aiohttp connects.

    It reduces SSRF TOCTOU risk by:
    - resolving inside the connector path
    - rejecting blocked IPs
    - detecting unstable DNS answers (basic rebinding detection)
    """

    def __init__(self, client: "SubscriptionHTTPClient"):
        self._client = client

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: int = socket.AF_UNSPEC,
    ) -> list[dict[str, object]]:
        normalized_host = self._client._normalize_host(host)

        if self._client._is_blocked_hostname(normalized_host):
            raise ExternalFetchError(
                url=host,
                reason="Blocked hostname",
            )

        # First resolution.
        infos_1 = await asyncio.to_thread(
            socket.getaddrinfo,
            normalized_host,
            port,
            family,
            socket.SOCK_STREAM,
        )
        ips_1 = self._client._extract_ips_from_getaddrinfo(infos_1)

        if not ips_1:
            raise ExternalFetchError(
                url=host,
                reason="Host did not resolve",
            )

        self._client._validate_resolved_ips(normalized_host, ips_1)

        # Second resolution to detect obvious rebinding / instability.
        infos_2 = await asyncio.to_thread(
            socket.getaddrinfo,
            normalized_host,
            port,
            family,
            socket.SOCK_STREAM,
        )
        ips_2 = self._client._extract_ips_from_getaddrinfo(infos_2)

        if set(ips_1) != set(ips_2):
            raise ExternalFetchError(
                url=host,
                reason="DNS rebinding detected",
            )

        # Return the first validated result set.
        results: list[dict[str, object]] = []
        seen: set[tuple[str, int, int, int]] = set()

        for info in infos_1:
            if not info or len(info) < 5:
                continue

            fam, socktype, proto, _canonname, sockaddr = info
            if not sockaddr:
                continue

            ip_str = sockaddr[0]
            key = (ip_str, fam, socktype, proto)
            if key in seen:
                continue
            seen.add(key)

            results.append(
                {
                    "hostname": normalized_host,
                    "host": ip_str,
                    "port": port,
                    "family": fam,
                    "proto": proto,
                    "flags": 0,
                }
            )

        if not results:
            raise ExternalFetchError(
                url=host,
                reason="No usable DNS answers",
            )

        return results

    async def close(self) -> None:
        return None


class SubscriptionHTTPClient:
    """
    Hardened async HTTP client for fetching external subscriptions.
    """

    def __init__(
        self,
        timeout: int = settings.fetch_timeout,
        user_agent: str = settings.fetch_user_agent,
        max_bytes: int = getattr(settings, "fetch_max_bytes", 2 * 1024 * 1024),
    ):
        self.timeout = timeout
        self.user_agent = user_agent
        self.max_bytes = max_bytes
        self._session: Optional[aiohttp.ClientSession] = None
        self._resolver: Optional[_GuardedResolver] = None

    @property
    def _is_production(self) -> bool:
        return getattr(settings, "environment", "").lower() == "production"

    def _normalize_host(self, host: str) -> str:
        return host.rstrip(".").lower()

    def _is_blocked_hostname(self, host: str) -> bool:
        normalized = self._normalize_host(host)
        return normalized in _BLOCKED_HOSTNAMES

    def _is_blocked_ip(self, ip: ipaddress._BaseAddress) -> bool:
        """
        Block anything that is not clearly public.
        """
        if ip in _BLOCKED_METADATA_IPS:
            return True

        if isinstance(ip, ipaddress.IPv6Address):
            mapped = ip.ipv4_mapped
            if mapped is not None:
                return self._is_blocked_ip(mapped)

        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
            or ip.is_reserved
            or getattr(ip, "is_site_local", False)
        )

    def _extract_ips_from_getaddrinfo(self, infos: list[tuple]) -> list[str]:
        ips: list[str] = []
        for info in infos:
            if not info or len(info) < 5:
                continue
            sockaddr = info[4]
            if not sockaddr:
                continue
            ip_str = sockaddr[0]
            ips.append(ip_str)
        return list(dict.fromkeys(ips))

    def _validate_resolved_ips(self, host: str, ips: list[str]) -> None:
        if not ips:
            raise ExternalFetchError(url=host, reason="Host did not resolve")

        for ip_str in ips:
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue

            if self._is_blocked_ip(ip):
                raise ExternalFetchError(
                    url=host,
                    reason=f"Blocked target IP: {ip_str}",
                )

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)

        if parsed.scheme not in {"http", "https"}:
            raise ExternalFetchError(url=url, reason="Invalid URL scheme")

        if not parsed.hostname:
            raise ExternalFetchError(url=url, reason="Missing hostname")

        if len(parsed.hostname.split(".")) < 2:
            raise ExternalFetchError(url=url, reason="Invalid hostname")

        # Avoid credentialed URLs in fetch targets.
        if parsed.username or parsed.password:
            raise ExternalFetchError(url=url, reason="Credentials in URL are not allowed")

    def _validate_no_ip_literal_in_url(self, url: str) -> None:
        """
        Block direct IP-literal targets in production.
        DNS names are allowed, but their resolved addresses are validated by the resolver.
        """
        if not self._is_production:
            return

        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            return

        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return

        raise ExternalFetchError(url=url, reason=f"Direct IP targets are blocked: {ip}")

    def _validate_content_type(
        self,
        headers: aiohttp.typedefs.LooseHeaders,
        url: str
    ) -> None:
        """
        Strict subscription Content-Type validator.
    
        Разрешает только текстовые форматы конфигов:
        - text/plain (V2Ray base64 / VLESS / VMess)
    
        Всё остальное запрещено.
        """
    
        content_type = headers.get("Content-Type", "").lower()
        base_type = content_type.split(";")[0].strip()
    
        # строго разрешённые типы
        allowed_types = {
            "text/plain",
        }
    
        if base_type in allowed_types:
            return
    
        raise ExternalFetchError(
            url=url,
            reason=f"Unsupported Content-Type for subscription: {base_type}",
        )

    def _validate_content_encoding(self, headers: aiohttp.typedefs.LooseHeaders, url: str) -> None:
        """
        Проверка Content-Encoding.
        Защита от zip bombs и подозрительных кодировок.
        """
        encoding = headers.get("Content-Encoding", "").lower()
        
        # Разрешенные кодировки
        allowed = {"gzip", "deflate", "br", "identity", ""}
        
        if encoding and encoding not in allowed:
            raise ExternalFetchError(
                url=url,
                reason=f"Suspicious Content-Encoding: {encoding}",
            )

    def _check_executable_signature(self, content: bytes, url: str) -> None:
        """
        Проверка на magic bytes исполняемых файлов.
        """
        if len(content) < 4:
            return
        
        for signature in _EXECUTABLE_SIGNATURES:
            if content.startswith(signature):
                raise ExternalFetchError(
                    url=url,
                    reason="Executable content detected",
                )

    def _check_malicious_patterns(self, content: bytes, url: str) -> None:
        """
        Проверка на вредоносные паттерны в контенте.
        """
        # Проверяем первые N байт для производительности
        check_size = min(len(content), 100000)  # 100KB
        sample = content[:check_size]
        
        for pattern in _MALICIOUS_PATTERNS:
            if pattern.search(sample):
                logger.warning(
                    "Malicious pattern detected in %s: %s",
                    url,
                    pattern.pattern.decode('utf-8', errors='replace')[:50]
                )
                raise ExternalFetchError(
                    url=url,
                    reason="Potentially malicious content detected",
                )

    def _validate_content_structure(self, content: str, url: str) -> None:
        """
        Валидация структуры контента.
        Защита от billion laughs attack и других DoS атак.
        """
        lines = content.split('\n')
        
        if len(lines) > _MAX_LINES:
            raise ExternalFetchError(
                url=url,
                reason=f"Too many lines (> {_MAX_LINES}), possible DoS attack",
            )
        
        # Проверка на чрезмерное повторение (защита от compression bombs)
        if len(content) > 1000:
            # Проверяем ratio уникальных символов
            unique_chars = len(set(content[:10000]))
            if unique_chars < 10:  # Слишком мало уникальных символов
                raise ExternalFetchError(
                    url=url,
                    reason="Suspicious content pattern detected",
                )

    def _sanitize_content(self, content: str) -> str:
        """
        Санитизация контента перед возвратом.
        Удаляет потенциально опасные элементы.
        """
        # Удаляем null bytes
        content = content.replace('\x00', '')
        
        # Удаляем control characters (кроме \n, \r, \t)
        content = ''.join(
            char for char in content 
            if char in '\n\r\t' or not (0 <= ord(char) < 32)
        )
        
        return content.strip()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout_obj = aiohttp.ClientTimeout(total=self.timeout)
            self._resolver = _GuardedResolver(self)

            connector = aiohttp.TCPConnector(
                resolver=self._resolver,
                use_dns_cache=False,
                ttl_dns_cache=0,
                limit=20,
                force_close=False,
                ssl=True,
            )

            self._session = aiohttp.ClientSession(
                timeout=timeout_obj,
                connector=connector,
                headers={"User-Agent": self.user_agent},
                trust_env=False,
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        self._resolver = None

    def validate_url_static(self, url: str) -> None:
        self._validate_url(url)
        self._validate_no_ip_literal_in_url(url)

        parsed = urlparse(url)
        host = parsed.hostname or ""

        if self._is_blocked_hostname(host):
            raise ExternalFetchError(url=url, reason="Blocked hostname")

    async def _fetch_once(
        self,
        session: aiohttp.ClientSession,
        url: str,
    ) -> tuple[int, str | None, aiohttp.typedefs.LooseHeaders, str]:
        async with session.get(url, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=self.timeout)) as response:
            # Сначала проверяем статус — редиректы и ошибки не имеют осмысленного тела
            if response.status in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                return response.status, location, response.headers, ""

            if response.status != 200:
                return response.status, None, response.headers, ""

            # Валидируем заголовки только для успешных ответов с телом
            self._validate_content_type(response.headers, url)
            self._validate_content_encoding(response.headers, url)

            total = 0
            chunks: list[bytes] = []

            async for chunk in response.content.iter_chunked(4096):
                total += len(chunk)
                if total > self.max_bytes:
                    raise ExternalFetchError(
                        url=url,
                        reason=f"Response too large (> {self.max_bytes} bytes)",
                        status_code=response.status,
                    )
                chunks.append(chunk)

            raw = b"".join(chunks)
            
            # Проверка на executable content
            self._check_executable_signature(raw, url)
            
            # Проверка на вредоносные паттерны
            self._check_malicious_patterns(raw, url)
            
            # Декодирование с валидацией
            try:
                text = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                # Пробуем другие кодировки
                for encoding in ["latin-1", "cp1252", "iso-8859-1"]:
                    try:
                        text = raw.decode(encoding, errors="strict")
                        logger.warning("Used fallback encoding %s for %s", encoding, url)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    # Если ничего не подошло, используем replace
                    text = raw.decode("utf-8", errors="replace")
                    logger.warning("Used UTF-8 with errors='replace' for %s", url)
            
            # Валидация структуры контента
            self._validate_content_structure(text, url)
            
            # Санитизация
            text = self._sanitize_content(text)
            
            return response.status, None, response.headers, text

    async def fetch(self, url: str) -> str:
        session = await self._get_session()
        current_url = url
    
        self._validate_url(current_url)
        self._validate_no_ip_literal_in_url(current_url)
    
        for attempt in range(3):
            try:
                logger.info(
                    "Fetching external subscription: %s (attempt %d)",
                    current_url,
                    attempt + 1,
                )
    
                parsed = urlparse(current_url)
    
                if self._is_blocked_hostname(parsed.hostname or ""):
                    raise ExternalFetchError(url=current_url, reason="Blocked hostname")
    
                status, _, _, body = await self._fetch_once(session, current_url)
    
                # --- HTTP логика ---
                if status in {301, 302, 303, 307, 308}:
                    raise ExternalFetchError(
                        url=url,
                        reason="Redirect not allowed",
                        status_code=status,
                    )
    
                if status != 200:
                    raise ExternalFetchError(
                        url=url,
                        reason=f"HTTP {status}",
                        status_code=status,
                    )
    
                content = body.strip()
    
                logger.info(
                    "Successfully fetched %d bytes from %s",
                    len(content.encode("utf-8", errors="replace")),
                    url,
                )
    
                return content
    
            # --- RETRY: сетевые ошибки и разрыв соединения ---
            except (
                aiohttp.ClientConnectorError,
                aiohttp.ServerTimeoutError,
                asyncio.TimeoutError,
                aiohttp.ClientOSError,
                aiohttp.ServerDisconnectedError,  # переиспользованное соединение закрыто сервером
            ) as e:
    
                if attempt == 2:
                    raise ExternalFetchError(
                        url=url,
                        reason=f"Network error: {type(e).__name__}",
                    ) from e
    
                delay = 2 ** attempt  # 1s, 2s
                logger.warning(
                    "Network error on %s (attempt %d): %s. Retrying in %ss",
                    url,
                    attempt + 1,
                    e,
                    delay,
                )
    
                await asyncio.sleep(delay)
    
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()


# ═══════════════════════════════════════════════════════════════════════════
# Global HTTP Client Instance
# ═══════════════════════════════════════════════════════════════════════════

_http_client: Optional[SubscriptionHTTPClient] = None


def get_http_client() -> SubscriptionHTTPClient:
    global _http_client
    if _http_client is None:
        _http_client = SubscriptionHTTPClient()
    return _http_client


async def close_http_client() -> None:
    global _http_client
    if _http_client:
        await _http_client.close()
        _http_client = None
