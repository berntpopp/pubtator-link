"""Deploy contract guard: the fleet controller's runtime observer proves the
effective container uid from /proc, so the deployed NPM overlay must declare a
numeric non-root `user` for every service; the release Compose files feed the
shared release gate (`container_release.py validate-compose`), which forbids a
non-numeric or root `user` there but — unlike most sibling repos — this repo's
`container-release.json` already contracts an explicit numeric `user` for the
`pubtator-postgres` auxiliary sidecar, so the release files legitimately carry
`user` and the guard checks it is numeric non-root rather than asserting absence."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]  # tests/unit/ -> repo root

NUMERIC_USER = re.compile(r"^[1-9][0-9]*:[1-9][0-9]*$")


class _TagTolerantLoader(yaml.SafeLoader):
    """SafeLoader that tolerates Compose's custom merge tags (!reset, !override)."""


_TagTolerantLoader.add_multi_constructor(
    "!",
    lambda loader, suffix, node: (
        loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None
    ),
)


def _load_compose(path: Path) -> dict:
    # _TagTolerantLoader subclasses yaml.SafeLoader (no arbitrary object construction);
    # ruff cannot see that through the subclass indirection.
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_TagTolerantLoader)  # noqa: S506


def test_npm_overlay_declares_numeric_user_for_every_service() -> None:
    compose = _load_compose(ROOT / "docker" / "docker-compose.npm.yml")
    for name, service in compose["services"].items():
        user = service.get("user")
        assert user is not None, f"{name} must declare a numeric user in the NPM overlay"
        assert NUMERIC_USER.match(str(user)), (
            f"{name} declares user={user!r}; the deploy contract requires "
            "'<uid>:<gid>' with both non-root and numeric"
        )


def test_release_compose_user_is_numeric_non_root_when_present() -> None:
    # Do NOT assert absence here: container-release.json's declared auxiliary
    # contract for pubtator-postgres pins an exact `user: "999:999"`, and
    # tests/unit/docker/test_container_release_auxiliary.py already proves the
    # release Compose render matches it exactly. This guard only has to keep any
    # `user` that does appear in the release files numeric and non-root.
    release_config = json.loads((ROOT / "container-release.json").read_text(encoding="utf-8"))
    for rel_path in release_config["service"]["compose_files"]:
        compose = _load_compose(ROOT / rel_path)
        for name, service in compose["services"].items():
            user = service.get("user")
            if user is None:
                continue
            assert NUMERIC_USER.match(str(user)), (
                f"{name} in {rel_path} declares user={user!r}; the release gate "
                "requires a numeric non-root uid:gid where 'user' is present"
            )
