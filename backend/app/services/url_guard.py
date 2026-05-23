"""URL 검증 — SSRF 차단 (PRD §11 보안).

전략:
1. 스킴은 http/https만 허용
2. 호스트네임 정규화 (IDN punycode)
3. hostname을 DNS resolve → 모든 IP가 공인(public)인지 검증
4. 호출자는 resolve된 IP 중 하나를 그대로 fetch에 넘겨 DNS rebinding 공격 차단

차단 대상 (PRD §11):
- 사설 IP: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
- 루프백: 127.0.0.0/8, ::1
- 링크로컬: 169.254.0.0/16 (AWS metadata 169.254.169.254 포함), fe80::/10
- 멀티캐스트, 예약된 대역, 0.0.0.0/8 등
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse


_ALLOWED_SCHEMES = {"http", "https"}
_MAX_URL_LENGTH = 2048


class UnsafeUrlError(ValueError):
    """SSRF 위험이 있거나 형식이 잘못된 URL — 사용자에게 그대로 메시지 노출 가능."""


@dataclass(frozen=True)
class SafeUrl:
    original: str
    scheme: str
    hostname: str  # punycode 정규화된 호스트
    port: Optional[int]
    resolved_ips: tuple[str, ...]  # 모두 public이 확인된 IP


def _is_public_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return False
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False
    # IPv4 0.0.0.0/8 등은 is_unspecified로 잡히지 않을 수 있어 보수적으로 처리
    if isinstance(ip, ipaddress.IPv4Address) and (
        ip in ipaddress.ip_network("0.0.0.0/8")
        or ip in ipaddress.ip_network("100.64.0.0/10")  # CGNAT
    ):
        return False
    return True


def validate_url(raw_url: str) -> SafeUrl:
    if not raw_url or len(raw_url) > _MAX_URL_LENGTH:
        raise UnsafeUrlError("유효하지 않은 URL입니다.")

    try:
        parsed = urlparse(raw_url)
    except ValueError as e:
        raise UnsafeUrlError("URL을 해석할 수 없습니다.") from e

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError("http 또는 https URL만 지원합니다.")

    hostname = parsed.hostname
    if not hostname:
        raise UnsafeUrlError("URL에 호스트가 없습니다.")

    # IDN → punycode 정규화. ascii로 변환 실패하면 거부.
    try:
        host_ascii = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as e:
        raise UnsafeUrlError("호스트 이름을 해석할 수 없습니다.") from e

    # 호스트가 그대로 IP 리터럴이면 즉시 검증 (DNS 안 거침)
    try:
        ipaddress.ip_address(host_ascii)
        candidate_ips: list[str] = [host_ascii]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host_ascii, None)
        except socket.gaierror as e:
            raise UnsafeUrlError("호스트 이름을 찾을 수 없습니다.") from e
        candidate_ips = list({info[4][0] for info in infos})

    if not candidate_ips:
        raise UnsafeUrlError("호스트 IP를 찾을 수 없습니다.")

    for ip in candidate_ips:
        if not _is_public_ip(ip):
            raise UnsafeUrlError("내부망/사설 IP는 분석할 수 없습니다.")

    return SafeUrl(
        original=raw_url,
        scheme=parsed.scheme.lower(),
        hostname=host_ascii,
        port=parsed.port,
        resolved_ips=tuple(candidate_ips),
    )
