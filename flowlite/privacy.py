"""Keep every byte on this machine.

Wispr Flow streams audio + screen/textbox context to Baseten/Modal and telemetry to
PostHog/Sentry. FlowLite does none of that; this module enforces it at runtime by
refusing any socket connection to a non-loopback address from this process.
Model downloads happen once, in `python -m flowlite.setup`, before the guard is on.
"""

import ipaddress
import os
import socket

_installed = False


def _is_loopback(host):
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False  # hostnames other than localhost are not allowed


def _address_host(address):
    if isinstance(address, tuple) and address:
        return str(address[0])
    return None  # AF_UNIX / pipes are local by definition


class OutboundBlocked(OSError):
    pass


def install():
    """Block outbound network access for this process (loopback stays allowed)."""
    global _installed
    if _installed:
        return
    # Hugging Face / faster-whisper: use the local cache only, no telemetry.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo

    def check(address):
        host = _address_host(address)
        if host is not None and not _is_loopback(host):
            raise OutboundBlocked(f"FlowLite privacy guard blocked a connection to {host}")

    def connect(self, address):
        check(address)
        return original_connect(self, address)

    def connect_ex(self, address):
        check(address)
        return original_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if host is not None and not _is_loopback(str(host)):
            raise OutboundBlocked(f"FlowLite privacy guard blocked a DNS lookup for {host}")
        return original_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo
    _installed = True
