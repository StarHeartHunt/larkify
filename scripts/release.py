"""Bump the version, regenerate CHANGELOG.md, then commit and tag the release.

The version comes from the commits since the last tag, unless one is given:

    uv run python scripts/release.py [VERSION]

Nothing is pushed. Pushing the tag publishes to PyPI and can't be taken back, so
that step is left to .github/workflows/release.yml, once the result looks right.
"""

import subprocess
import sys


def run(*command: str) -> str:
    result = subprocess.run(command, check=True, stdout=subprocess.PIPE, text=True)
    return result.stdout.strip()


def main() -> None:
    if run("git", "branch", "--show-current") != "main":
        sys.exit("Releases are made from main.")
    if run("git", "status", "--porcelain"):
        sys.exit("The working tree has uncommitted changes.")

    if len(sys.argv) > 1:
        tag = f"v{sys.argv[1].removeprefix('v')}"
    else:
        tag = run("git-cliff", "--bumped-version")
    # git-cliff answers with the last tag when there is nothing to release.
    if run("git", "tag", "--list", tag):
        sys.exit(f"{tag} already exists.")

    run("uv", "version", tag.removeprefix("v"))
    run("git-cliff", "--tag", tag, "--output", "CHANGELOG.md")
    run("git", "add", "pyproject.toml", "uv.lock", "CHANGELOG.md")
    run("git", "commit", "--message", f"chore(release): {tag}")
    run("git", "tag", "--annotate", tag, "--message", tag)

    print(f"Tagged {tag}. To publish it:\n\n    git push --atomic origin main {tag}")


if __name__ == "__main__":
    main()
