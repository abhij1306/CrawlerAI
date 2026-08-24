from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import threading
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

from app.core.config.runtime_settings import crawler_runtime_settings
from app.core.url_safety import validate_proxy_endpoint, validate_public_target

logger = logging.getLogger(__name__)

_SOCKS_VERSION = 5
_SOCKS_CMD_CONNECT = 1
_SOCKS_AUTH_NONE = 0
_SOCKS_AUTH_USERPASS = 2
_SOCKS_AUTH_NO_ACCEPTABLE = 0xFF
_SOCKS_ATYP_IPV4 = 1
_SOCKS_ATYP_DOMAIN = 3
_SOCKS_ATYP_IPV6 = 4
_SOCKS_REPLY_GENERAL_FAILURE = 1
_SOCKS_REPLY_COMMAND_NOT_SUPPORTED = 7
_BRIDGE_COUNTERS = {
    "opened": 0,
    "closed": 0,
    "failures": 0,
}
_BRIDGE_COUNTERS_LOCK = threading.Lock()


def _increment_bridge_counter(name: str) -> None:
    with _BRIDGE_COUNTERS_LOCK:
        _BRIDGE_COUNTERS[name] += 1


class _ClientNotifiedSocksError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Socks5UpstreamProxy:
    scheme: str
    host: str
    port: int
    username: str
    password: str


def parse_socks5_upstream_proxy(proxy_url: str | None) -> Socks5UpstreamProxy | None:
    raw_proxy = str(proxy_url or "").strip()
    if not raw_proxy:
        return None
    parsed = urlparse(raw_proxy)
    scheme = str(parsed.scheme or "").strip().lower()
    if scheme not in {"socks5", "socks5h"}:
        return None
    if not parsed.hostname or parsed.port is None:
        return None
    username = unquote(str(parsed.username or ""))
    password = unquote(str(parsed.password or ""))
    return Socks5UpstreamProxy(
        scheme=scheme,
        host=str(parsed.hostname),
        port=int(parsed.port),
        username=username,
        password=password,
    )


class Socks5AuthBridge:
    def __init__(self, upstream: Socks5UpstreamProxy | None = None) -> None:
        self.upstream = upstream
        self._server: asyncio.AbstractServer | None = None
        self._server_url: str | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._start_lock = asyncio.Lock()

    async def start(self) -> str:
        async with self._start_lock:
            if self._server is not None and self._server_url is not None:
                return self._server_url
            server = await asyncio.start_server(
                self._handle_client,
                host="127.0.0.1",
                port=0,
            )
            sockets = list(server.sockets or [])
            if not sockets:
                server.close()
                await server.wait_closed()
                _increment_bridge_counter("failures")
                raise RuntimeError("SOCKS5 auth bridge failed to bind a local socket")
            port = int(sockets[0].getsockname()[1])
            self._server = server
            self._server_url = f"socks5://127.0.0.1:{port}"
            _increment_bridge_counter("opened")
            return self._server_url

    async def close(self) -> None:
        server = self._server
        self._server = None
        self._server_url = None
        if server is not None:
            server.close()
            await server.wait_closed()
            _increment_bridge_counter("closed")
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _open_direct(
        self,
        host: str,
        port: int,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=float(
                crawler_runtime_settings.browser_proxy_bridge_connect_timeout_seconds
            ),
        )

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._tasks.add(task)
        upstream_writer: asyncio.StreamWriter | None = None
        try:
            request = await asyncio.wait_for(
                _read_client_request(reader, writer),
                timeout=float(
                    crawler_runtime_settings.browser_proxy_bridge_first_byte_timeout_seconds
                ),
            )
            target = await validate_public_target(request.validation_url())
            pinned_ip = target.resolved_ips[0]
            if self.upstream is None:
                opened_reader, opened_writer = await self._open_direct(
                    pinned_ip,
                    request.port_number,
                )
                upstream_writer = opened_writer
                writer.write(_success_response())
                await writer.drain()
                await asyncio.gather(
                    _relay_stream(reader, opened_writer),
                    _relay_stream(opened_reader, writer),
                )
                return
            upstream_target = await validate_proxy_endpoint(
                f"{self.upstream.scheme}://{self.upstream.host}:{self.upstream.port}"
            )
            opened_reader, opened_writer = await asyncio.wait_for(
                asyncio.open_connection(
                    upstream_target.resolved_ips[0],
                    self.upstream.port,
                ),
                timeout=float(
                    crawler_runtime_settings.browser_proxy_bridge_connect_timeout_seconds
                ),
            )
            upstream_writer = opened_writer
            await asyncio.wait_for(
                _authenticate_upstream(
                    opened_reader,
                    opened_writer,
                    upstream=self.upstream,
                ),
                timeout=float(
                    crawler_runtime_settings.browser_proxy_bridge_auth_timeout_seconds
                ),
            )
            opened_writer.write(request.to_upstream_bytes(host=pinned_ip))
            await opened_writer.drain()
            response = await asyncio.wait_for(
                _read_socks5_response(opened_reader),
                timeout=float(
                    crawler_runtime_settings.browser_proxy_bridge_first_byte_timeout_seconds
                ),
            )
            writer.write(response)
            await writer.drain()
            if response[1] != 0:
                return
            await asyncio.gather(
                _relay_stream(reader, opened_writer),
                _relay_stream(opened_reader, writer),
            )
        except _ClientNotifiedSocksError:
            _increment_bridge_counter("failures")
            logger.debug("SOCKS5 auth bridge rejected client request", exc_info=True)
        except Exception:
            _increment_bridge_counter("failures")
            logger.debug("SOCKS5 auth bridge request failed", exc_info=True)
            with contextlib.suppress(Exception):
                writer.write(_failure_response(_SOCKS_REPLY_GENERAL_FAILURE))
                await writer.drain()
        finally:
            if task is not None:
                self._tasks.discard(task)
            if upstream_writer is not None:
                upstream_writer.close()
                with contextlib.suppress(Exception):
                    await upstream_writer.wait_closed()
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()


@dataclass(frozen=True, slots=True)
class _Socks5ConnectRequest:
    header: bytes
    address: bytes
    port: bytes

    @property
    def port_number(self) -> int:
        return int.from_bytes(self.port, "big")

    def validation_url(self) -> str:
        host = _decode_request_host(self.header[3], self.address)
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"http://{host}:{self.port_number}/"

    def to_upstream_bytes(self, *, host: str | None = None) -> bytes:
        if host is None:
            return self.header + self.address + self.port
        address_type, address = _encode_request_host(host)
        header = bytes([self.header[0], self.header[1], self.header[2], address_type])
        return header + address + self.port


async def _read_client_request(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> _Socks5ConnectRequest:
    header = await reader.readexactly(2)
    version, method_count = header[0], header[1]
    if version != _SOCKS_VERSION:
        raise ValueError(f"Unsupported SOCKS version: {version}")
    methods = await reader.readexactly(method_count)
    if _SOCKS_AUTH_NONE not in methods:
        writer.write(bytes([_SOCKS_VERSION, _SOCKS_AUTH_NO_ACCEPTABLE]))
        await writer.drain()
        raise _ClientNotifiedSocksError(
            "Browser SOCKS client did not offer no-auth method"
        )
    writer.write(bytes([_SOCKS_VERSION, _SOCKS_AUTH_NONE]))
    await writer.drain()
    request_header = await reader.readexactly(4)
    version, command, _reserved, address_type = request_header
    if version != _SOCKS_VERSION:
        raise ValueError(f"Unsupported SOCKS request version: {version}")
    if command != _SOCKS_CMD_CONNECT:
        writer.write(_failure_response(_SOCKS_REPLY_COMMAND_NOT_SUPPORTED))
        await writer.drain()
        raise _ClientNotifiedSocksError(f"Unsupported SOCKS command: {command}")
    address_bytes = await _read_address_bytes(reader, address_type)
    port_bytes = await reader.readexactly(2)
    return _Socks5ConnectRequest(
        header=request_header,
        address=address_bytes,
        port=port_bytes,
    )


async def _authenticate_upstream(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    upstream: Socks5UpstreamProxy,
) -> None:
    if upstream.username or upstream.password:
        writer.write(bytes([_SOCKS_VERSION, 1, _SOCKS_AUTH_USERPASS]))
    else:
        writer.write(bytes([_SOCKS_VERSION, 1, _SOCKS_AUTH_NONE]))
    await writer.drain()

    response = await reader.readexactly(2)
    if response[0] != _SOCKS_VERSION:
        raise ValueError(f"Unexpected upstream SOCKS version: {response[0]}")
    method = response[1]
    if method == _SOCKS_AUTH_NONE:
        return
    if method != _SOCKS_AUTH_USERPASS:
        raise ValueError(f"Unsupported upstream SOCKS auth method: {method}")

    username = upstream.username.encode("utf-8")
    password = upstream.password.encode("utf-8")
    if len(username) > 255 or len(password) > 255:
        raise ValueError("SOCKS5 proxy username/password too long")
    writer.write(
        bytes([1, len(username)]) + username + bytes([len(password)]) + password
    )
    await writer.drain()
    auth_response = await reader.readexactly(2)
    if auth_response[1] != 0:
        raise ValueError("SOCKS5 upstream authentication failed")


async def _read_socks5_response(reader: asyncio.StreamReader) -> bytes:
    header = await reader.readexactly(4)
    _version, _reply, _reserved, address_type = header
    if _version != _SOCKS_VERSION:
        raise ValueError(f"Unexpected upstream SOCKS response version: {_version}")
    address_bytes = await _read_address_bytes(reader, address_type)
    port_bytes = await reader.readexactly(2)
    return header + address_bytes + port_bytes


def _decode_request_host(address_type: int, address: bytes) -> str:
    if address_type == _SOCKS_ATYP_IPV4:
        return str(ipaddress.IPv4Address(address))
    if address_type == _SOCKS_ATYP_IPV6:
        return str(ipaddress.IPv6Address(address))
    if address_type == _SOCKS_ATYP_DOMAIN:
        if not address or address[0] != len(address) - 1:
            raise ValueError("Invalid SOCKS5 domain address")
        return address[1:].decode("idna")
    raise ValueError(f"Unsupported SOCKS address type: {address_type}")


def _encode_request_host(host: str) -> tuple[int, bytes]:
    try:
        ip_value = ipaddress.ip_address(host)
    except ValueError:
        encoded = host.encode("idna")
        if len(encoded) > 255:
            raise ValueError("SOCKS5 target hostname too long")
        return _SOCKS_ATYP_DOMAIN, bytes([len(encoded)]) + encoded
    if isinstance(ip_value, ipaddress.IPv4Address):
        return _SOCKS_ATYP_IPV4, ip_value.packed
    return _SOCKS_ATYP_IPV6, ip_value.packed


def _success_response() -> bytes:
    return bytes(
        [
            _SOCKS_VERSION,
            0,
            0,
            _SOCKS_ATYP_IPV4,
            0,
            0,
            0,
            0,
            0,
            0,
        ]
    )


async def _read_address_bytes(
    reader: asyncio.StreamReader,
    address_type: int,
) -> bytes:
    if address_type == _SOCKS_ATYP_IPV4:
        return await reader.readexactly(4)
    if address_type == _SOCKS_ATYP_IPV6:
        return await reader.readexactly(16)
    if address_type == _SOCKS_ATYP_DOMAIN:
        length_byte = await reader.readexactly(1)
        length = length_byte[0]
        return length_byte + await reader.readexactly(length)
    raise ValueError(f"Unsupported SOCKS address type: {address_type}")


async def _relay_stream(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    finally:
        with contextlib.suppress(Exception):
            writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


def _failure_response(reply_code: int) -> bytes:
    return bytes(
        [
            _SOCKS_VERSION,
            reply_code,
            0,
            _SOCKS_ATYP_IPV4,
            0,
            0,
            0,
            0,
            0,
            0,
        ]
    )


def bridge_counters() -> dict[str, int]:
    with _BRIDGE_COUNTERS_LOCK:
        return dict(_BRIDGE_COUNTERS)


def reset_bridge_counters() -> None:
    with _BRIDGE_COUNTERS_LOCK:
        for key in _BRIDGE_COUNTERS:
            _BRIDGE_COUNTERS[key] = 0
