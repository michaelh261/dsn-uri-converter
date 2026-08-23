"""Conversion between libpq-style DSN strings and URI-style connection strings.

DSN form:  host=localhost port=5432 dbname=mydb user=admin password='a b'
URI form:  postgresql://admin:a%20b@localhost:5432/mydb

Both forms show up depending on which tool you're feeding: psql and most
libpq-based drivers want the DSN, everything built around DATABASE_URL
(Flask, Rails, most 12-factor deploys) wants the URI. Nobody wants to
hand-translate quoting rules between the two, hence this.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

# DSN keys that map onto a dedicated field rather than the free-form params
# dict. Anything not listed here is preserved as-is (e.g. sslmode, connect_timeout).
_DSN_TO_FIELD = {
    "host": "host",
    "port": "port",
    "dbname": "database",
    "user": "username",
    "password": "password",
}
_FIELD_TO_DSN = {v: k for k, v in _DSN_TO_FIELD.items()}


@dataclass
class ConnectionParams:
    scheme: str = "postgresql"
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    params: Dict[str, str] = field(default_factory=dict)


def _tokenize_dsn(dsn: str):
    """Split a DSN into (key, value) pairs, honoring single-quoted values.

    libpq DSNs allow values like host='my host' password='it\\'s a secret'
    where whitespace inside quotes doesn't end the token and backslash
    escapes the next character.
    """
    pairs = []
    i, n = 0, len(dsn)
    while i < n:
        while i < n and dsn[i].isspace():
            i += 1
        if i >= n:
            break

        start = i
        while i < n and dsn[i] != "=":
            i += 1
        if i >= n:
            raise ValueError(f"malformed dsn near {dsn[start:]!r}: missing '='")
        key = dsn[start:i].strip()
        i += 1  # skip '='

        if i < n and dsn[i] == "'":
            i += 1
            chars = []
            while i < n and dsn[i] != "'":
                if dsn[i] == "\\" and i + 1 < n:
                    chars.append(dsn[i + 1])
                    i += 2
                else:
                    chars.append(dsn[i])
                    i += 1
            if i >= n:
                raise ValueError(f"unterminated quoted value for key {key!r}")
            i += 1  # skip closing quote
            value = "".join(chars)
        else:
            vstart = i
            while i < n and not dsn[i].isspace():
                i += 1
            value = dsn[vstart:i]

        pairs.append((key, value))
    return pairs


def _quote_dsn_value(value: str) -> str:
    if value == "" or "'" in value or "\\" in value or any(c.isspace() for c in value):
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    return value


def parse_dsn(dsn: str) -> ConnectionParams:
    """Parse a libpq-style DSN into a ConnectionParams."""
    params = ConnectionParams()
    extra = {}
    for key, value in _tokenize_dsn(dsn):
        field_name = _DSN_TO_FIELD.get(key)
        if field_name == "port":
            params.port = int(value)
        elif field_name is not None:
            setattr(params, field_name, value)
        else:
            extra[key] = value
    params.params = extra
    return params


def to_dsn(params: ConnectionParams) -> str:
    """Render a ConnectionParams as a libpq-style DSN string."""
    parts = []
    if params.host:
        parts.append(f"host={_quote_dsn_value(params.host)}")
    if params.port:
        parts.append(f"port={params.port}")
    if params.database:
        parts.append(f"dbname={_quote_dsn_value(params.database)}")
    if params.username:
        parts.append(f"user={_quote_dsn_value(params.username)}")
    if params.password:
        parts.append(f"password={_quote_dsn_value(params.password)}")
    for key, value in params.params.items():
        parts.append(f"{key}={_quote_dsn_value(value)}")
    return " ".join(parts)


def parse_uri(uri: str) -> ConnectionParams:
    """Parse a scheme://user:pass@host:port/db?params URI into a ConnectionParams."""
    split = urlsplit(uri)
    if not split.scheme:
        raise ValueError(f"not a valid connection uri (missing scheme): {uri!r}")

    params = ConnectionParams(scheme=split.scheme)
    if split.hostname:
        params.host = split.hostname
    if split.port:
        params.port = split.port
    if split.username:
        params.username = unquote(split.username)
    if split.password:
        params.password = unquote(split.password)

    database = split.path.lstrip("/")
    if database:
        params.database = unquote(database)

    params.params = dict(parse_qsl(split.query))
    return params


def to_uri(params: ConnectionParams, scheme: Optional[str] = None) -> str:
    """Render a ConnectionParams as a scheme://user:pass@host:port/db?params URI."""
    scheme = scheme or params.scheme or "postgresql"

    auth = ""
    if params.username:
        auth = quote(params.username, safe="")
        if params.password:
            auth += f":{quote(params.password, safe='')}"
        auth += "@"

    host = params.host or "localhost"
    netloc = f"{auth}{host}"
    if params.port:
        netloc += f":{params.port}"

    path = f"/{quote(params.database, safe='')}" if params.database else ""
    query = f"?{urlencode(params.params)}" if params.params else ""

    return f"{scheme}://{netloc}{path}{query}"
