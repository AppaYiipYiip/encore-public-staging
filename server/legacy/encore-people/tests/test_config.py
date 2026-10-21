"""The settings read from the environment."""
import os
import unittest
from unittest import mock

from encore_people.config import Config


class ConfigTest(unittest.TestCase):
    def owners(self, value: str | None) -> frozenset[str]:
        env = {} if value is None else {"PEOPLE_INVITERS": value}
        with mock.patch.dict(os.environ, env, clear=True):
            return Config.from_env().owners

    def test_nobody_is_named_by_default(self) -> None:
        self.assertEqual(self.owners(None), frozenset())
        self.assertEqual(self.owners(""), frozenset())

    def test_names_are_split_trimmed_and_lower_cased(self) -> None:
        self.assertEqual(self.owners("owner, Sara ,,ben"), frozenset({"owner", "sara", "ben"}))


if __name__ == "__main__":
    unittest.main()
