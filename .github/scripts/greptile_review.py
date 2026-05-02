"""Post a Greptile code review comment on a GitHub PR.

Called from .github/workflows/greptile-review.yaml. Reads all inputs from
environment variables so nothing from GitHub context is interpolated into
shell commands.
"""

from __future__ import annotations

import os

import httpx

GREPTILE_API_URL = "https://api.greptile.com/v2"

GREPTILE_API_KEY = os.environ["GREPTILE_API_KEY"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ["GITHUB_REPOSITORY"]
PR_NUMBER = os.environ["PR_NUMBER"]
PR_TITLE = os.environ["PR_TITLE"]
PR_BODY = os.environ.get("PR_BODY", "")
BASE_BRANCH = os.environ["BASE_BRANCH"]
HEAD_BRANCH = os.environ["HEAD_BRANCH"]

GREPTILE_HEADERS = {
    "Authorization": f"Bearer {GREPTILE_API_KEY}",
    "X-GitHub-Token": GITHUB_TOKEN,
    "Content-Type": "application/json",
}
GITHUB_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}


def get_pr_files() -> list[dict]:
    url = f"https://api.github.com/repos/{REPO}/pulls/{PR_NUMBER}/files"
    files = []
    page = 1
    while True:
        r = httpx.get(url, headers=GITHUB_HEADERS, params={"per_page": 100, "page": page})
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        files.extend(batch)
        page += 1
    return files


def build_diff_summary(files: list[dict], max_files: int = 25) -> str:
    parts = []
    for f in files[:max_files]:
        patch = f.get("patch", "")
        status = f.get("status", "")
        name = f["filename"]
        header = f"### {name} ({status}, +{f['additions']}/-{f['deletions']})"
        parts.append(f"{header}\n```diff\n{patch[:3000]}\n```" if patch else header)
    if len(files) > max_files:
        parts.append(f"*... and {len(files) - max_files} more files not shown.*")
    return "\n\n".join(parts)


def query_greptile(diff_summary: str) -> str:
    prompt = f"""\
Review this pull request for the Mori Python agent library.

PR: "{PR_TITLE}"
Branch: `{HEAD_BRANCH}` → `{BASE_BRANCH}`
{f'Description: {PR_BODY}' if PR_BODY else ''}

Focus on:
- Type safety gaps (missing annotations, incorrect types vs protocol)
- Protocol/abstract base conformance (MemoryBackend, ModelAdapter, etc.)
- Optional-import guard pattern violations (mori/model/anthropic.py is the reference)
- Async lifecycle issues (missing close(), resource leaks)
- Spec compliance — does the implementation match mori-docs/specs/?
- Security issues (secrets in logs, unsafe deserialization, injection)
- Real bugs only — skip style nits, vague suggestions, and "consider" comments

Be specific and actionable. Only flag real problems. Most files need no comments.

## Changed files

{diff_summary}
"""
    r = httpx.post(
        f"{GREPTILE_API_URL}/query",
        headers=GREPTILE_HEADERS,
        json={
            "messages": [{"role": "user", "content": prompt}],
            "repositories": [{"remote": "github", "repository": REPO, "branch": BASE_BRANCH}],
            "genius": True,
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["message"]


def delete_previous_greptile_comments() -> None:
    url = f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/comments"
    r = httpx.get(url, headers=GITHUB_HEADERS, params={"per_page": 100})
    r.raise_for_status()
    for comment in r.json():
        if comment.get("body", "").startswith("## Greptile Review"):
            httpx.delete(
                f"https://api.github.com/repos/{REPO}/issues/comments/{comment['id']}",
                headers=GITHUB_HEADERS,
            )


def post_comment(body: str) -> None:
    r = httpx.post(
        f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/comments",
        headers=GITHUB_HEADERS,
        json={"body": body},
    )
    r.raise_for_status()


def main() -> None:
    print(f"Fetching files for PR #{PR_NUMBER} in {REPO}...")
    files = get_pr_files()
    print(f"  {len(files)} files changed")

    diff_summary = build_diff_summary(files)

    print("Querying Greptile...")
    review = query_greptile(diff_summary)

    print("Posting review comment...")
    delete_previous_greptile_comments()
    post_comment(
        f"## Greptile Review\n\n{review}\n\n---\n*Reviewed by [Greptile](https://greptile.com)*"
    )
    print("Done.")


if __name__ == "__main__":
    main()
