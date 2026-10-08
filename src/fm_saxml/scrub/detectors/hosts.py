"""Internal hostnames, private IPs and home-directory usernames.

Public hosts are left alone; only names that identify private infrastructure
(private IPv4 ranges, single-label hosts, internal TLDs) or an employee's
machine account are replaced.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Iterable

from ..policy import ScrubPolicy
from . import Hit

_INTERNAL_TLD_RE = re.compile(r"\.(?:local|internal|lan|intranet|corp|home|test|example|invalid|localdomain)$", re.I)
_IPV4_SHAPE_RE = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}")

# Network schemes: the host follows the slashes (fmnet uses a single slash).
_URL_HOST_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:https?|ftps?|sftp|scp|smb|ldaps?|wss?|fmp\d*|fmnet):/{1,3}"
    r"(?:[^\s\"'/@\\]*@)?([A-Za-z0-9._-]+)",
    re.I,
)
# File schemes only name a host in their UNC form (filewin://server/share); a
# single slash is followed by a drive or volume name, not a host.
_FILE_HOST_RE = re.compile(r"(?<![A-Za-z0-9])(?:filewin|filemac|file)://([A-Za-z0-9._-]+)", re.I)
# \\SERVER\share. Inside calc strings the backslashes are doubled. Not after a
# drive colon or a word, so C:\\Users\\x isn't read as host "Users".
_UNC_RE = re.compile(r"(?<![\w:\\\]])\\{2,}([A-Za-z0-9._-]+)(?=\\)")
# A bare hostname (no scheme) is only recognisable by an unmistakably internal TLD.
_BARE_HOST_RE = re.compile(
    r"(?<![\w./\-\[])((?:[A-Za-z0-9-]+\.)+(?:local|internal|lan|intranet|corp|localdomain))(?![\w.\-])", re.I
)
_IP_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
_POSIX_HOME_RE = re.compile(r"/(?:Users|home)/([A-Za-z0-9._-]+)")
_WIN_HOME_RE = re.compile(r"[A-Za-z]:\\{1,2}Users\\{1,2}([^\\/\"'\r\n\t]+?)(?=\\|/|$|[\"'\s])", re.I)

_KEEP_USERS = {"shared", "public", "default", "default user", "all users"}


# Explicit ranges rather than IPv4Address.is_private, which also counts netmasks
# (255.255.255.0) and documentation ranges.
_PRIVATE_NETS = tuple(ipaddress.IPv4Network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16", "100.64.0.0/10",
))


def is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    return any(addr in net for net in _PRIVATE_NETS)


def is_internal_host(host: str) -> bool:
    host = host.rstrip(".")
    if _IPV4_SHAPE_RE.fullmatch(host):
        return is_private_ip(host)
    if host.lower() == "localhost" or len(host) < 2:
        return False
    if "." not in host:
        return True
    return bool(_INTERNAL_TLD_RE.search(host))


def detect(text: str, policy: ScrubPolicy) -> Iterable[Hit]:
    if ":/" in text:
        for pattern in (_URL_HOST_RE, _FILE_HOST_RE):
            for m in pattern.finditer(text):
                if is_internal_host(m.group(1)):
                    yield Hit(*m.span(1), "host", "internal_host", 60)
    if "\\\\" in text:
        for m in _UNC_RE.finditer(text):
            if is_internal_host(m.group(1)):
                yield Hit(*m.span(1), "host", "unc_host", 60)
    if "." in text:
        for m in _BARE_HOST_RE.finditer(text):
            # After emails (70): jane@corp.local stays one [EMAIL] rather than jane@[HOST].
            yield Hit(*m.span(1), "host", "internal_host", 75)
        for m in _IP_RE.finditer(text):
            if is_private_ip(m.group(1)):
                yield Hit(*m.span(1), "host", "private_ip", 61)
    if "/" in text:
        for m in _POSIX_HOME_RE.finditer(text):
            if m.group(1).lower() not in _KEEP_USERS:
                yield Hit(*m.span(1), "user", "home_directory", 60)
    if "\\" in text:
        for m in _WIN_HOME_RE.finditer(text):
            if m.group(1).strip().lower() not in _KEEP_USERS:
                yield Hit(*m.span(1), "user", "home_directory", 60)
