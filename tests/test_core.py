"""Round-trip tests for passwords containing characters that are special to
either the DSN quoting rules (space, quote, backslash) or URI percent-encoding
(@, %, #, /, etc). A converter that mishandles any of these silently corrupts
a credential instead of erroring, so these are worth pinning down explicitly.
"""

import unittest

from connstr_convert.core import ConnectionParams, parse_dsn, parse_uri, to_dsn, to_uri

SPECIAL_PASSWORDS = [
    "plain",
    "with space",
    "trailing space ",
    " leading space",
    "quo'te",
    "back\\slash",
    "back\\slash'and'quote",
    "at@sign",
    "percent%20literal",
    "hash#fragment",
    "slash/es",
    "amp&ersand",
    "equals=sign",
    "colon:here",
    "question?mark",
    "semi;colon",
    "plus+sign",
    "unicode-é日本語",
    "",
]


class DsnRoundTrip(unittest.TestCase):
    def test_password_survives_dsn_round_trip(self):
        for password in SPECIAL_PASSWORDS:
            with self.subTest(password=password):
                params = ConnectionParams(
                    host="localhost",
                    port=5432,
                    database="mydb",
                    username="admin",
                    password=password,
                )
                reparsed = parse_dsn(to_dsn(params))
                self.assertEqual(reparsed.password, password or None)

    def test_password_survives_uri_round_trip(self):
        for password in SPECIAL_PASSWORDS:
            with self.subTest(password=password):
                params = ConnectionParams(
                    scheme="postgresql",
                    host="localhost",
                    port=5432,
                    database="mydb",
                    username="admin",
                    password=password,
                )
                reparsed = parse_uri(to_uri(params))
                self.assertEqual(reparsed.password, password or None)

    def test_password_survives_dsn_to_uri_to_dsn(self):
        for password in SPECIAL_PASSWORDS:
            if not password:
                continue  # an empty password is indistinguishable from "no password" in both formats
            with self.subTest(password=password):
                original = ConnectionParams(
                    host="localhost", database="mydb", username="admin", password=password
                )
                via_uri = parse_uri(to_uri(original))
                back_to_dsn = parse_dsn(to_dsn(via_uri))
                self.assertEqual(back_to_dsn.password, password)

    def test_password_survives_uri_to_dsn_to_uri(self):
        for password in SPECIAL_PASSWORDS:
            if not password:
                continue
            with self.subTest(password=password):
                original = ConnectionParams(
                    scheme="postgresql",
                    host="localhost",
                    database="mydb",
                    username="admin",
                    password=password,
                )
                via_dsn = parse_dsn(to_dsn(original))
                back_to_uri = parse_uri(to_uri(via_dsn))
                self.assertEqual(back_to_uri.password, password)

    def test_quoted_dsn_literal_with_embedded_quote_and_backslash(self):
        dsn = r"host=localhost dbname=mydb user=admin password='it\'s a \\secret'"
        parsed = parse_dsn(dsn)
        self.assertEqual(parsed.password, "it's a \\secret")

        uri = to_uri(parsed)
        self.assertEqual(parse_uri(uri).password, "it's a \\secret")


if __name__ == "__main__":
    unittest.main()
