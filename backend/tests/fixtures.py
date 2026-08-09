from pathlib import Path


def _find_examples_dir(start: Path) -> Path:
    """Locate data/examples above `start`. A fixed parents[n] depth would
    break depending on whether tests run via a host venv (repo root two
    levels above backend/tests, per DEVELOPMENT.md/CI) or inside the dev
    container (where docker-compose.dev.yml mounts it at /app/data/examples,
    one level above /app/tests) — so search instead of assuming either.
    """
    for parent in (start, *start.parents):
        candidate = parent / "data" / "examples"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"could not locate data/examples above {start}")


EXAMPLES_DIR = _find_examples_dir(Path(__file__).resolve())
