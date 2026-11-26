"""Test-only login values, generated fresh for every test run.

No password is written in the test code, so secret scanners have nothing to flag and
nothing real can leak. The same label gives the same value within one run.
"""
import secrets

_RUN = secrets.token_hex(6)


def pw(label: str) -> str:
    return f"{label}-{_RUN}"
