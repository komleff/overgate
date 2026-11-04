#!/usr/bin/env python3
"""Адресный producer/consumer gate для активных имён WI-C."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
MAPPING = {
    "u2-with-timeout.": ("overgate-with-timeout.", (".claude/tools/with-timeout.sh",)),
    "U2_WITH_TIMEOUT_TEST_STARTUP_PAUSE_SECONDS": (
        "OVERGATE_WITH_TIMEOUT_TEST_STARTUP_PAUSE_SECONDS",
        (".claude/tools/with-timeout.sh", "scripts/tests/with-timeout-transparency.test.sh"),
    ),
    "U2_UNKNOWN_SUBCOMMAND": (
        "OVERGATE_UNKNOWN_SUBCOMMAND",
        (".claude/hooks/commit_command_classifier.py", "scripts/tests/commit-command-classifier.test.sh"),
    ),
    "u2-pre-bash-": ("overgate-pre-bash-", ("scripts/tests/pre-bash-dispatch.test.py",)),
    "u2-outside-": ("overgate-outside-", ("scripts/tests/pre-bash-dispatch.test.py",)),
    "u2-publisher-test-": ("overgate-publisher-test-", ("scripts/tests/publish-pr-comment.test.py",)),
}


def violations(contents: dict[str, str]) -> list[str]:
    result = []
    for old, (new, paths) in MAPPING.items():
        for name in paths:
            text = contents[name]
            if old in text or new not in text:
                result.append(f"{name}: active {old} / missing {new}")
    return result


class ActiveNames(unittest.TestCase):
    def test_producers_and_consumers_are_generic(self):
        contents = {name: (ROOT / name).read_text(encoding="utf-8")
                    for _, paths in MAPPING.values() for name in paths}
        self.assertEqual(violations(contents), [])

    def test_each_old_name_mutation_is_detected(self):
        contents = {name: (ROOT / name).read_text(encoding="utf-8")
                    for _, paths in MAPPING.values() for name in paths}
        self.assertEqual(violations(contents), [])
        for old, (new, paths) in MAPPING.items():
            for name in paths:
                with self.subTest(name=name, old=old):
                    changed = dict(contents)
                    changed[name] = changed[name].replace(new, old, 1)
                    self.assertTrue(violations(changed))


if __name__ == "__main__":
    unittest.main(verbosity=2)
