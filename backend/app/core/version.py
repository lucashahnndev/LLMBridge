from __future__ import annotations

import re
from functools import total_ordering


APP_VERSION = "0.3.8"
SCHEMA_BASE_VERSION = "0.1.0"
SCHEMA_VERSION = "0.3.8"

_SEMVER_PATTERN = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


@total_ordering
class SemVer:
    def __init__(self, value: str) -> None:
        match = _SEMVER_PATTERN.match(value.strip())
        if not match:
            raise ValueError(f"Invalid semantic version: {value}")
        self.major = int(match.group("major"))
        self.minor = int(match.group("minor"))
        self.patch = int(match.group("patch"))
        self.prerelease = match.group("prerelease")

    def _key(self) -> tuple[int, int, int, int, str]:
        # Stable releases sort after prereleases for the same numeric triplet.
        prerelease_rank = 1 if self.prerelease is None else 0
        return (self.major, self.minor, self.patch, prerelease_rank, self.prerelease or "")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self._key() == other._key()

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self._key() < other._key()


def compare_semver(left: str, right: str) -> int:
    left_version = SemVer(left)
    right_version = SemVer(right)
    if left_version < right_version:
        return -1
    if left_version > right_version:
        return 1
    return 0
