# dsn-uri-converter

Database connection strings come in two incompatible shapes depending on
which tool you're talking to:

- **DSN form** (libpq, psql, most C-based drivers): `host=localhost port=5432 dbname=mydb user=admin password=secret`
- **URI form** (SQLAlchemy, DATABASE_URL-style 12-factor configs, most ORMs): `postgresql://admin:secret@localhost:5432/mydb`

They're both just key/value pairs underneath, but the quoting rules are
different enough (URI percent-encoding vs. DSN single-quote escaping) that
translating one to the other by hand is a good way to lose an afternoon to a
password with a `@` or `%` in it. This converts between them.

## Usage

As a library:

```python
from connstr_convert import parse_dsn, to_uri

params = parse_dsn("host=localhost port=5432 dbname=mydb user=admin password='p@ss w0rd'")
print(to_uri(params))
# postgresql://admin:p%40ss%20w0rd@localhost:5432/mydb
```

```python
from connstr_convert import parse_uri, to_dsn

params = parse_uri("mysql://admin:p%40ss@db.internal:3306/orders?sslmode=require")
print(to_dsn(params))
# host=db.internal port=3306 dbname=orders user=admin password=p@ss sslmode=require
```

From the command line:

```
$ python -m connstr_convert.cli "host=localhost port=5432 dbname=mydb user=admin" --to uri
postgresql://admin@localhost:5432/mydb

$ python -m connstr_convert.cli "postgresql://admin@localhost/mydb" --to dsn
host=localhost dbname=mydb user=admin
```

Or, once installed (`pip install -e .`), as the `connstr-convert` command:

```
$ connstr-convert "host=localhost dbname=mydb user=admin" --to uri --scheme mysql
mysql://admin@localhost/mydb
```

Input format is auto-detected: anything containing `://` is treated as a
URI, everything else is treated as a DSN.

## What's handled

- Quoted DSN values with spaces and escaped quotes (`password='it\'s secret'`)
- Percent-encoding of usernames, passwords, and database names in URIs
- Arbitrary extra parameters (`sslmode`, `connect_timeout`, etc.) carried
  through in both directions
- Multi-host DSNs and URIs for replica/failover setups, e.g.
  `host=primary,replica port=5432,5433` or
  `postgresql://user@primary:5432,replica:5433/db`
- IPv6 host literals in URIs, bracketed per RFC 3986
  (`postgresql://user@[::1]:5432/db`), including in multi-host lists
- `sqlite://` URIs, where the path is a filesystem path rather than a host:
  `sqlite:///relative.db` (relative) vs. `sqlite:////absolute/path.db`
  (absolute), and `sqlite:///:memory:`
- Round-tripping a value through both converters gives back the same
  connection info, even when it contains reserved characters

## Requirements

Python 3.9+, standard library only.

## Testing

```
$ python -m unittest discover
```

## License

MIT, see LICENSE.
