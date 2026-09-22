"""Conversion between libpq-style DSN strings and URI-style connection strings.

DSN form:  host=localhost port=5432 dbname=mydb user=admin password='a b'
URI form:  postgresql://admin:a%20b@localhost:5432/mydb

Both forms show up depending on which tool you're feeding: psql and most
libpq-based drivers want the DSN, everything built around DATABASE_URL
(Flask, Rails, most 12-factor deploys) wants the URI. Nobody wants to
hand-translate quoting rules between the two, hence this.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
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
    # Set instead of host/port for multi-host DSNs (replica/failover lists:
    # host=primary,replica1,replica2). Empty for the single-host case.
    hosts: List[Tuple[str, Optional[int]]] = field(default_factory=list)


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
    """Parse a libpq-style DSN into a ConnectionParams.

    host and port accept comma-separated lists for replica/failover setups
    (host=primary,replica port=5432,5433), per libpq's multi-host DSN rules:
    a single port applies to every host, otherwise the port count must match
    the host count.
    """
    params = ConnectionParams()
    extra = {}
    host_raw = None
    port_raw = None
    for key, value in _tokenize_dsn(dsn):
        if key == "host":
            host_raw = value
            continue
        if key == "port":
            port_raw = value
            continue
        field_name = _DSN_TO_FIELD.get(key)
        if field_name is not None:
            setattr(params, field_name, value)
        else:
            extra[key] = value
    params.params = extra

    if host_raw is not None:
        hosts = [h.strip() for h in host_raw.split(",")]
        ports = [p.strip() for p in port_raw.split(",")] if port_raw is not None else []
        if len(ports) > 1 and len(ports) != len(hosts):
            raise ValueError(
                f"host/port count mismatch in dsn: {len(hosts)} host(s), "
                f"{len(ports)} port(s)"
            )
        if len(hosts) > 1:
            if not ports:
                resolved_ports = [None] * len(hosts)
            elif len(ports) == 1:
                resolved_ports = [int(ports[0])] * len(hosts) if ports[0] else [None] * len(hosts)
            else:
                resolved_ports = [int(p) if p else None for p in ports]
            params.hosts = list(zip(hosts, resolved_ports))
        else:
            params.host = hosts[0]
            if ports and ports[0]:
                params.port = int(ports[0])
    return params


def to_dsn(params: ConnectionParams) -> str:
    """Render a ConnectionParams as a libpq-style DSN string."""
    parts = []
    if params.hosts:
        parts.append(
            f"host={_quote_dsn_value(','.join(h for h, _ in params.hosts))}"
        )
        if any(p is not None for _, p in params.hosts):
            port_list = ",".join(str(p) if p is not None else "" for _, p in params.hosts)
            parts.append(f"port={_quote_dsn_value(port_list)}")
    else:
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


def _split_hostport(chunk: str) -> Tuple[str, Optional[int]]:
    """Split a host[:port] chunk, understanding bracketed IPv6 literals.

    A bare rpartition(":") breaks on "[::1]" (no port), since the address
    itself is full of colons: it would carve off "1]" as the port. Brackets
    have to be located explicitly before falling back to the simple case.
    """
    chunk = chunk.strip()
    if chunk.startswith("["):
        end = chunk.find("]")
        if end == -1:
            raise ValueError(f"unterminated ipv6 literal in host: {chunk!r}")
        host = chunk[1:end]
        rest = chunk[end + 1 :]
        if rest.startswith(":"):
            return host, int(rest[1:])
        return host, None
    host, sep, port = chunk.rpartition(":")
    if sep:
        return host, int(port)
    return chunk, None


def _format_host(host: str) -> str:
    """Wrap an IPv6 literal in brackets for use in a URI netloc."""
    return f"[{host}]" if ":" in host else host


def parse_uri(uri: str) -> ConnectionParams:
    """Parse a scheme://user:pass@host:port/db?params URI into a ConnectionParams.

    Also accepts a comma-separated host list in place of a single host, as
    used by libpq-derived clients for replica/failover URIs:
    scheme://user:pass@host1:port1,host2:port2/db
    """
    split = urlsplit(uri)
    if not split.scheme:
        raise ValueError(f"not a valid connection uri (missing scheme): {uri!r}")

    params = ConnectionParams(scheme=split.scheme)

    _, _, hostinfo = split.netloc.rpartition("@")
    if "," in hostinfo:
        # split.hostname/.port assume a single host:port and choke on the
        # extra commas and colons, so parse the host list by hand.
        params.hosts = [_split_hostport(chunk) for chunk in hostinfo.split(",")]
    else:
        if split.hostname:
            params.host = split.hostname
        if split.port:
            params.port = split.port
    if split.username:
        params.username = unquote(split.username)
    if split.password:
        params.password = unquote(split.password)

    if split.scheme == "sqlite":
        # sqlite uris hold a filesystem path, not a host: there's no netloc,
        # and the path keeps a leading slash for the absolute case
        # (sqlite:////abs/path.db) vs. none for the relative case
        # (sqlite:///rel/path.db). A plain lstrip("/") would erase that
        # distinction, so only the one slash that separates "://" from the
        # path is dropped.
        if split.path:
            params.database = unquote(split.path[1:])
    else:
        database = split.path.lstrip("/")
        if database:
            params.database = unquote(database)

    params.params = dict(parse_qsl(split.query))
    return params


def to_uri(params: ConnectionParams, scheme: Optional[str] = None) -> str:
    """Render a ConnectionParams as a scheme://user:pass@host:port/db?params URI."""
    scheme = scheme or params.scheme or "postgresql"

    if scheme.lower() == "sqlite":
        # no host/user/port for a file-based database; see parse_uri for why
        # the leading slash is added back rather than stripped.
        path = f"/{quote(params.database, safe='/:')}" if params.database else "/"
        query = f"?{urlencode(params.params)}" if params.params else ""
        return f"{scheme}://{path}{query}"

    auth = ""
    if params.username:
        auth = quote(params.username, safe="")
        if params.password:
            auth += f":{quote(params.password, safe='')}"
        auth += "@"

    if params.hosts:
        netloc = auth + ",".join(
            f"{_format_host(h)}:{p}" if p is not None else _format_host(h)
            for h, p in params.hosts
        )
    else:
        # No host means "local unix socket", per libpq and mysqlclient alike
        # (mysql://user:pass@/db?unix_socket=/var/run/mysqld/mysqld.sock is
        # the standard mysql idiom for this). Filling in "localhost" here
        # would silently turn that into a TCP connection.
        host = _format_host(params.host) if params.host else ""
        netloc = f"{auth}{host}"
        if params.port:
            netloc += f":{params.port}"

    path = f"/{quote(params.database, safe='')}" if params.database else ""
    query = f"?{urlencode(params.params)}" if params.params else ""

    return f"{scheme}://{netloc}{path}{query}"
