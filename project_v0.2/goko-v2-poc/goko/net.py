"""Prefer IPv4 when resolving hosts.

Python's urllib tries addresses in resolver order, one after another, each with
the full timeout. On a machine whose IPv6 route is broken but still advertised,
every connection to a dual-stack host (Gemini, OpenAI) waits out one timeout per
IPv6 address before reaching IPv4 -- measured here at ~55 s per call. Browsers and
curl race the two families and never notice. Putting IPv4 answers first keeps
IPv6 as a fallback and removes the stall.
"""
import socket

_orig = socket.getaddrinfo


def _ipv4_first(*args, **kwargs):
    res = _orig(*args, **kwargs)
    return sorted(res, key=lambda r: r[0] != socket.AF_INET)


def prefer_ipv4():
    if socket.getaddrinfo is not _ipv4_first:
        socket.getaddrinfo = _ipv4_first
