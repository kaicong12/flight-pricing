"""One outbound HTTP client, shared so the worker reuses connections.

Verification goes through the OS trust store rather than certifi: under corporate TLS interception
the intercepting root is installed system-wide, so curl succeeds where certifi-only Python fails.
"""

import os
import ssl
from functools import lru_cache

import httpx
import truststore

DEFAULT_TIMEOUT = 40.0


@lru_cache
def _verify() -> ssl.SSLContext:
    bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if bundle:
        return ssl.create_default_context(cafile=bundle)
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


@lru_cache
def client() -> httpx.Client:
    return httpx.Client(verify=_verify(), timeout=DEFAULT_TIMEOUT, follow_redirects=True)
