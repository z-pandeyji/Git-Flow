from __future__ import annotations

import re
import shutil
import subprocess
import uuid
import os
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from .models import Repo
from .storage import REPOS_DIR, ensure_storage


GITHUB_RE = re.compile(r"^https://github\.com/([^/\s]+)/([^/\s#?]+?)(?:\.git)?/?$")


class ScanInputError(ValueError):
    pass


def validate_public_github_url(repo_url: str) -> tuple[str, str]:
    match = GITHUB_RE.match(repo_url.strip())
    if not match:
        raise ScanInputError("Use a public GitHub repository URL like https://github.com/owner/repo.")
    owner, name = match.groups()
    if not owner or not name:
        raise ScanInputError("GitHub repository URL is missing an owner or repository name.")
    return owner, name


def clone_public_repo(repo_url: str) -> Repo:
    ensure_storage()
    owner, name = validate_public_github_url(repo_url)
    repo_id = f"{owner}-{name}-{uuid.uuid4().hex[:8]}"
    destination = REPOS_DIR / repo_id
    if destination.exists():
        shutil.rmtree(destination)
    git_error = ""
    try:
        _run_git(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", repo_url, str(destination)])
        _run_git(["git", "-C", str(destination), "sparse-checkout", "set", "--no-cone", *_sparse_paths(name)])
    except subprocess.TimeoutExpired as exc:
        git_error = "git clone timed out"
        _reset_destination(destination)
        _download_archive(owner, name, destination, git_error)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or "git clone failed"
        git_error = stderr
        _reset_destination(destination)
        _download_archive(owner, name, destination, git_error)
    return Repo(id=repo_id, url=repo_url, name=name, owner=owner, local_path=str(destination))


def _run_git(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=int(os.getenv("BFO_GIT_TIMEOUT_SECONDS", "75")))


def _reset_destination(destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)


def _download_archive(owner: str, name: str, destination: Path, git_error: str) -> None:
    errors = []
    for branch in ["main", "master"]:
        url = f"https://github.com/{owner}/{name}/archive/refs/heads/{branch}.zip"
        try:
            with urllib.request.urlopen(url, timeout=int(os.getenv("BFO_GIT_TIMEOUT_SECONDS", "75"))) as response:
                archive_bytes = response.read()
            archive_path = destination.parent / f"{destination.name}.zip"
            archive_path.write_bytes(archive_bytes)
            with zipfile.ZipFile(archive_path) as archive:
                root_names = _safe_extract_archive(archive, destination.parent)
            archive_path.unlink(missing_ok=True)
            extracted_root = destination.parent / sorted(root_names)[0]
            if destination.exists():
                shutil.rmtree(destination)
            extracted_root.rename(destination)
            return
        except (OSError, urllib.error.URLError, zipfile.BadZipFile, IndexError) as exc:
            errors.append(f"{branch}: {exc}")
    raise ScanInputError(f"Unable to clone repository. Git failed with: {git_error}. Archive fallback failed with: {'; '.join(errors)}")


def _safe_extract_archive(archive: zipfile.ZipFile, target_dir: Path) -> set[str]:
    target_root = target_dir.resolve()
    root_names: set[str] = set()
    for member in archive.infolist():
        if not member.filename:
            continue
        output_path = (target_dir / member.filename).resolve()
        if output_path != target_root and target_root not in output_path.parents:
            raise ScanInputError("Archive contains unsafe paths.")
        root_names.add(member.filename.split("/", 1)[0])
    archive.extractall(target_dir)
    return root_names


def _sparse_paths(repo_name: str) -> list[str]:
    normalized_name = re.sub(r"[^A-Za-z0-9]+", "-", repo_name).strip("-").lower()
    package_candidates = {
        normalized_name,
        normalized_name.replace("-", "_"),
        normalized_name.replace("_", "-"),
    }
    paths = [
        "/src/**",
        "/lib/**",
        "/app/**",
        "/apps/**",
        "/packages/**",
        "/tests/**",
        "/test/**",
        "/examples/**",
        "/backend/**",
        "/frontend/**",
        "/server/**",
        "/client/**",
        "/routes/**",
        "/controllers/**",
        "/services/**",
        "/workers/**",
        "/internal/**",
        "/bin/**",
        "/cmd/**",
        "/pkg/**",
        "/scripts/**",
        "/crates/**",
        "/headroom/**",
        "/sdk/**",
        "/plugins/**",
        "README.md",
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "Dockerfile",
        "docker-compose.yml",
    ]
    for candidate in sorted(package_candidates):
        if candidate:
            paths.append(f"/{candidate}/**")
    return paths


def create_demo_repo() -> Repo:
    ensure_storage()
    repo_id = f"demo-urbanseva-{uuid.uuid4().hex[:8]}"
    destination = REPOS_DIR / repo_id
    destination.mkdir(parents=True, exist_ok=True)
    files = {
        "package.json": """{"dependencies":{"express":"latest","zod":"latest"},"devDependencies":{"typescript":"latest"}}""",
        "src/app.ts": """
import express from 'express';
import { createBooking } from './booking.service';
import { notifyProvider } from './notification.service';

const app = express();
app.post('/booking', async (req, res) => {
  const booking = await createBooking(req.body);
  await notifyProvider(booking.providerId);
  res.json(booking);
});

app.post('/payments', async (req, res) => {
  res.json({ ok: true });
});
""",
        "src/booking.service.ts": """
import { findProvider } from './provider.service';
import { saveBooking } from './booking.repository';

export async function createBooking(input: any) {
  const provider = await findProvider(input.location);
  return saveBooking({ ...input, providerId: provider.id });
}
""",
        "src/provider.service.ts": """
export async function findProvider(location: string) {
  return { id: 'provider_1', location };
}
""",
        "src/notification.service.ts": """
export async function notifyProvider(providerId: string) {
  return fetch('https://notification.example.com/send', { method: 'POST', body: providerId });
}
""",
        "src/booking.repository.ts": """
export async function saveBooking(booking: any) {
  return { id: 'booking_1', ...booking };
}
""",
    }
    for relative, content in files.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.strip() + "\n", encoding="utf-8")
    return Repo(id=repo_id, url="demo://urbanseva", name="UrbanSeva Demo", owner="demo", local_path=str(destination))


def repo_name_from_url(repo_url: str) -> str:
    parsed = urlparse(repo_url)
    return Path(parsed.path).stem or "repository"
