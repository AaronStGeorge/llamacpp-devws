#!/usr/bin/env python3

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


ZERO_SHA = "0" * 40


class GitHubClient:
    def __init__(self, token: str, api_url: str) -> None:
        self.token = token
        self.api_url = api_url.rstrip("/")

    def request(self, url: str) -> bytes:
        request = urllib.request.Request(
            url,
            headers=self.api_headers(),
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()

    def api_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "llamacpp-devws-ci",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def request_json(
        self,
        path: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.api_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        try:
            return json.loads(self.request(url))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API request failed: {url}: {exc.code} {body}") from exc

    def download(self, url: str) -> bytes:
        try:
            return self.download_from_api_redirect(url)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub artifact download failed: {exc.code} {body}") from exc

    def download_from_api_redirect(self, url: str) -> bytes:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args: Any, **kwargs: Any) -> None:
                return None

        opener = urllib.request.build_opener(NoRedirect)
        request = urllib.request.Request(url, headers=self.api_headers())
        try:
            with opener.open(request, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in {301, 302, 303, 307, 308}:
                raise
            location = exc.headers.get("Location")
            if not location:
                raise RuntimeError("GitHub artifact download redirect did not include Location") from exc

        request = urllib.request.Request(
            location,
            headers={"User-Agent": "llamacpp-devws-ci"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()


def parent_sha_from_env() -> str:
    return os.environ.get("PARENT_SHA", "").strip()


def workflow_path_from_env(repo: str) -> str:
    workflow_ref = os.environ.get("GITHUB_WORKFLOW_REF", "")
    prefix = f"{repo}/"
    if workflow_ref.startswith(prefix):
        workflow_ref = workflow_ref[len(prefix) :]
    if "@" in workflow_ref:
        workflow_ref = workflow_ref.split("@", 1)[0]
    if workflow_ref.startswith(".github/workflows/"):
        return workflow_ref
    return ""


def repo_path(repo: str, suffix: str) -> str:
    return f"/repos/{repo}{suffix}"


def find_successful_run(
    client: GitHubClient,
    repo: str,
    parent_sha: str,
    workflow_name: str,
    workflow_path: str,
    current_run_id: str,
) -> dict[str, Any] | None:
    params = {
        "head_sha": parent_sha,
        "status": "success",
        "per_page": "100",
    }
    runs = client.request_json(repo_path(repo, "/actions/runs"), params).get(
        "workflow_runs",
        [],
    )
    if not isinstance(runs, list):
        raise RuntimeError("Unexpected GitHub API response: workflow_runs is not a list")

    for run in runs:
        if not isinstance(run, dict):
            continue
        if current_run_id and str(run.get("id")) == current_run_id:
            continue
        if run.get("head_sha") != parent_sha:
            continue
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            continue
        if workflow_path and run.get("path") != workflow_path:
            continue
        if not workflow_path and workflow_name and run.get("name") != workflow_name:
            continue
        return run
    return None


def find_artifact(
    client: GitHubClient,
    repo: str,
    run_id: int,
    artifact_name: str,
) -> dict[str, Any] | None:
    params = {"per_page": "100"}
    artifacts = client.request_json(
        repo_path(repo, f"/actions/runs/{run_id}/artifacts"),
        params,
    ).get("artifacts", [])
    if not isinstance(artifacts, list):
        raise RuntimeError("Unexpected GitHub API response: artifacts is not a list")

    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        if artifact.get("name") == artifact_name and not artifact.get("expired", False):
            return artifact
    return None


def safe_extract(zip_bytes: bytes, output_dir: Path) -> None:
    output_root = output_dir.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        for member in archive.infolist():
            target = (output_root / member.filename).resolve()
            if target != output_root and output_root not in target.parents:
                raise RuntimeError(
                    f"Refusing to extract artifact member outside output dir: {member.filename}"
                )
        archive.extractall(output_root)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download a previous successful workflow artifact for the parent commit."
    )
    parser.add_argument("artifact_name")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument(
        "--api-url",
        default=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
    )
    args = parser.parse_args()

    parent_sha = parent_sha_from_env()
    if not parent_sha:
        print("PARENT_SHA is required to download a previous benchmark artifact.", file=sys.stderr)
        raise SystemExit(2)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("GITHUB_TOKEN or GH_TOKEN is required to download GitHub artifacts.", file=sys.stderr)
        raise SystemExit(2)
    if not args.repo:
        print("GITHUB_REPOSITORY is required, or pass --repo owner/name.", file=sys.stderr)
        raise SystemExit(2)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    if parent_sha == ZERO_SHA:
        print("Parent commit is the all-zero SHA; skipping artifact download.")
        raise SystemExit(0)

    client = GitHubClient(token=token, api_url=args.api_url)
    workflow_name = os.environ.get("GITHUB_WORKFLOW", "")
    workflow_path = workflow_path_from_env(args.repo)
    current_run_id = os.environ.get("GITHUB_RUN_ID", "")

    run = find_successful_run(
        client=client,
        repo=args.repo,
        parent_sha=parent_sha,
        workflow_name=workflow_name,
        workflow_path=workflow_path,
        current_run_id=current_run_id,
    )
    if run is None:
        workflow_label = workflow_path or workflow_name or "current workflow"
        print(f"No successful {workflow_label} run found for parent commit {parent_sha}.")
        raise SystemExit(0)

    run_id = int(run["id"])
    artifact = find_artifact(client, args.repo, run_id, args.artifact_name)
    if artifact is None:
        print(f"Parent run {run_id} has no {args.artifact_name} artifact.")
        raise SystemExit(0)

    archive_url = str(artifact["archive_download_url"])
    zip_bytes = client.download(archive_url)
    safe_extract(zip_bytes, args.output_dir)
    print(
        f"Downloaded {args.artifact_name} from parent commit {parent_sha}, "
        f"run {run_id}, to {args.output_dir}."
    )


if __name__ == "__main__":
    main()
