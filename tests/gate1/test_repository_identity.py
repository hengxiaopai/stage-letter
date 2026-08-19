from __future__ import annotations

import unittest

from stage_letter.infrastructure.db.repositories.identity import (
    MAX_POSTGRES_BIGINT,
    PersistenceIdentityError,
    parse_persistence_id,
    serialize_persistence_id,
)


class RepositoryIdentityContractTests(unittest.TestCase):
    def test_positive_ascii_decimal_round_trips_losslessly(self) -> None:
        for value in ("1", "42", str(MAX_POSTGRES_BIGINT)):
            parsed = parse_persistence_id(value, field="account_id")
            self.assertEqual(value, serialize_persistence_id(parsed, field="account_id"))

    def test_zero_and_negative_values_are_rejected(self) -> None:
        for value in ("0", "-1"):
            with self.subTest(value=value):
                with self.assertRaises(PersistenceIdentityError):
                    parse_persistence_id(value, field="creator_id")

    def test_noncanonical_aliases_are_rejected(self) -> None:
        for value in ("01", "+1", " 1", "1 ", "1.0"):
            with self.subTest(value=value):
                with self.assertRaises(PersistenceIdentityError):
                    parse_persistence_id(value, field="session_id")

    def test_unicode_digits_are_rejected(self) -> None:
        with self.assertRaises(PersistenceIdentityError):
            parse_persistence_id("１２", field="user_id")

    def test_out_of_range_bigint_is_rejected(self) -> None:
        with self.assertRaises(PersistenceIdentityError):
            parse_persistence_id(str(MAX_POSTGRES_BIGINT + 1), field="account_id")

    def test_serializer_rejects_bool_non_int_and_invalid_range(self) -> None:
        for value in (True, 0, -1, MAX_POSTGRES_BIGINT + 1, 1.0):
            with self.subTest(value=value):
                with self.assertRaises(PersistenceIdentityError):
                    serialize_persistence_id(value, field="creator_id")  # type: ignore[arg-type]

    def test_formal_string_evidence_ids_are_not_numeric_identity_contracts(self) -> None:
        # observation_id/event_id have dedicated string columns. The repository
        # must preserve values such as these verbatim instead of coercing them
        # through BIGINT persistence identity helpers.
        for value in ("obs:streamget:abc", "event:live-started:uuid-like"):
            with self.subTest(value=value):
                with self.assertRaises(PersistenceIdentityError):
                    parse_persistence_id(value, field="formal_evidence_id")


if __name__ == "__main__":
    unittest.main()
