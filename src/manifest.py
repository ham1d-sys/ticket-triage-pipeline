import json
import os
import subprocess
from dataclasses import dataclass, field, asdict
from logging import getLogger
from pathlib import Path
from typing import Literal, Optional

logger = getLogger(__name__)


@dataclass
class CodeInfo:
    git_sha: str
    release: Optional[str]
    dirty: bool


@dataclass
class ConfigInfo:
    model: str
    prompt_sha256: str
    abort_count: int
    max_concurrency: int


@dataclass
class InputInfo:
    path: str
    sha256: str


@dataclass
class CountsInfo:
    loaded: int = 0
    invalid: int = 0
    skipped: int = 0
    triaged: int = 0
    needs_review: int = 0
    unattempted: int = 0


def git(*args: str, repo: str = ".") -> str:
    result = subprocess.run(["git", *args], cwd=Path(repo), capture_output=True, text=True, check=True)
    return result.stdout.strip()


def get_git_sha(repo: Path):
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def get_release_tag(repo: Path) -> str | None:
    try:
        return git("describe", "--tags", "--exact-match", "HEAD", repo=repo)
    except subprocess.CalledProcessError:
        return None


def is_dirty(repo: Path) -> bool:
    return bool(git("status", "--porcelain", repo=repo))


@dataclass
class Manifest:
    manifest_version: int
    run_id: str
    status: Literal["running", "aborted", "completed", "failed"]
    mode: Literal["production", "eval"]
    started_at: str
    code: CodeInfo
    config: ConfigInfo
    input: InputInfo
    counts: CountsInfo = field(default_factory=CountsInfo)
    finished_at: Optional[str] = None
    needs_review_breakdown: dict[str, int] = field(default_factory=dict)
    error: Optional[str] = None


def write_manifest(path: Path, manifest: Manifest):
    main = path / "manifest.json"
    tmp = main.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="UTF-8") as manifest_file:
        json.dump(asdict(manifest), manifest_file, indent=2)
        manifest_file.flush()
        os.fsync(manifest_file.fileno())
    os.replace(tmp, main)
    logger.info(f"Manifest written to '{main}'")
