#!/usr/bin/env bash
# Cut a new release of fm-saxml-converter.
#
#   ./release.sh            prompt for a version, check, bump, test, build, tag, push
#   ./release.sh --dry-run  run every check, test and build, but change nothing
#
# Steps:
#   1. Pre-flight: tools present, on master, clean tree, in sync with origin.
#   2. Prompt for MAJOR.MINOR.PATCH and make sure it is valid, newer than the
#      latest tag, and unused (local tag, remote tag, GitHub Release, PyPI).
#   3. Set __version__ in src/fm_saxml/__init__.py.
#   4. Run the test suite, build sdist + wheel, twine check, and smoke-test the
#      wheel in a throwaway venv (--version must match, doctor must pass).
#   5. After confirmation: commit the bump, push master, wait for CI to pass,
#      push an annotated vX.Y.Z tag and follow the Release workflow (which
#      builds the executables, creates the GitHub Release and publishes to PyPI).
#
# Requires: git, uv, curl, and gh (authenticated) for the CI/release steps.

set -euo pipefail

PACKAGE="fm-saxml-converter"
VERSION_FILE="src/fm_saxml/__init__.py"
MAIN_BRANCH="master"
REMOTE="origin"

cd "$(dirname "$0")"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
elif [[ $# -gt 0 ]]; then
    echo "Usage: $0 [--dry-run]" >&2
    exit 2
fi

# ---------------------------------------------------------------- helpers

if [[ -t 1 ]]; then
    BOLD=$'\e[1m' RED=$'\e[31m' GREEN=$'\e[32m' YELLOW=$'\e[33m' RESET=$'\e[0m'
else
    BOLD="" RED="" GREEN="" YELLOW="" RESET=""
fi

step() { echo; echo "${BOLD}==> $*${RESET}"; }
ok()   { echo "${GREEN}  ok${RESET} $*"; }
warn() { echo "${YELLOW}  warning:${RESET} $*"; }
die()  { echo "${RED}error:${RESET} $*" >&2; exit 1; }

confirm() {
    local reply
    read -r -p "$1 [y/N] " reply
    [[ "$reply" =~ ^[Yy]([Ee][Ss])?$ ]]
}

current_version() {
    sed -n 's/^__version__ = "\(.*\)"/\1/p' "$VERSION_FILE"
}

# Restore the version file if we bail out before the bump is committed.
ORIGINAL_VERSION_FILE=""
BUMP_COMMITTED=0
WORK_DIR=""
cleanup() {
    if [[ -n "$ORIGINAL_VERSION_FILE" && $BUMP_COMMITTED -eq 0 ]]; then
        printf '%s' "$ORIGINAL_VERSION_FILE" > "$VERSION_FILE"
        echo "Restored $VERSION_FILE."
    fi
    if [[ -n "$WORK_DIR" ]]; then
        rm -rf "$WORK_DIR"
    fi
}
trap cleanup EXIT

# ---------------------------------------------------------------- 1. pre-flight

step "Pre-flight checks"

for tool in git uv curl; do
    command -v "$tool" >/dev/null || die "'$tool' is not on PATH."
done
HAVE_GH=0
if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
    HAVE_GH=1
    ok "gh is installed and authenticated"
elif [[ $DRY_RUN -eq 1 ]]; then
    warn "gh is missing or not logged in; skipping the GitHub Release check."
else
    die "gh must be installed and logged in (run: gh auth login)."
fi

branch=$(git rev-parse --abbrev-ref HEAD)
[[ "$branch" == "$MAIN_BRANCH" ]] || die "On branch '$branch'; releases are cut from '$MAIN_BRANCH'."
ok "on $MAIN_BRANCH"

if [[ -n "$(git status --porcelain)" ]]; then
    if [[ $DRY_RUN -eq 1 ]]; then
        warn "working tree has uncommitted changes (allowed in --dry-run)."
    else
        git status --short
        die "Working tree is not clean. Commit or stash the changes above first."
    fi
else
    ok "working tree clean"
fi

git fetch --quiet --tags "$REMOTE" "$MAIN_BRANCH"
local_sha=$(git rev-parse HEAD)
remote_sha=$(git rev-parse "$REMOTE/$MAIN_BRANCH")
if [[ "$local_sha" != "$remote_sha" ]]; then
    if git merge-base --is-ancestor "$local_sha" "$remote_sha"; then
        die "Local $MAIN_BRANCH is behind $REMOTE/$MAIN_BRANCH. Pull first."
    elif ! git merge-base --is-ancestor "$remote_sha" "$local_sha"; then
        die "Local $MAIN_BRANCH has diverged from $REMOTE/$MAIN_BRANCH."
    fi
    warn "local $MAIN_BRANCH has unpushed commits; they will be pushed with the release."
else
    ok "in sync with $REMOTE/$MAIN_BRANCH"
fi

# ---------------------------------------------------------------- 2. version

step "Version"

current=$(current_version)
[[ -n "$current" ]] || die "Could not read __version__ from $VERSION_FILE."
latest_tag=$(git tag -l 'v*' | sed 's/^v//' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -n 1 || true)
echo "  __version__ in source: $current"
echo "  latest release tag:    ${latest_tag:+v}${latest_tag:-(none)}"

read -r -p "New version (MAJOR.MINOR.PATCH): " VERSION
VERSION="${VERSION#v}"
VERSION="${VERSION//[[:space:]]/}"

[[ "$VERSION" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] \
    || die "'$VERSION' is not a valid MAJOR.MINOR.PATCH version (e.g. 1.2.3)."
ok "$VERSION is well formed"

if [[ -n "$latest_tag" ]]; then
    highest=$(printf '%s\n%s\n' "$latest_tag" "$VERSION" | sort -V | tail -n 1)
    [[ "$VERSION" != "$latest_tag" && "$highest" == "$VERSION" ]] \
        || die "$VERSION is not newer than the latest release v$latest_tag."
    ok "newer than v$latest_tag"
fi

TAG="v$VERSION"

git rev-parse -q --verify "refs/tags/$TAG" >/dev/null \
    && die "Tag $TAG already exists locally."
[[ -n "$(git ls-remote --tags "$REMOTE" "refs/tags/$TAG")" ]] \
    && die "Tag $TAG already exists on $REMOTE."
ok "tag $TAG is unused"

if [[ $HAVE_GH -eq 1 ]]; then
    gh release view "$TAG" >/dev/null 2>&1 \
        && die "A GitHub Release named $TAG already exists."
    ok "no GitHub Release $TAG"
fi

pypi_status=$(curl -s -o /dev/null -w '%{http_code}' "https://pypi.org/pypi/$PACKAGE/$VERSION/json" || echo "000")
case "$pypi_status" in
    200) die "$PACKAGE $VERSION is already on PyPI (versions can never be reused)." ;;
    404) ok "$VERSION is not on PyPI" ;;
    *)   die "Could not check PyPI (HTTP $pypi_status). Check your connection and retry." ;;
esac

# ---------------------------------------------------------------- 3. bump

step "Setting __version__ to $VERSION"

if [[ "$current" == "$VERSION" ]]; then
    ok "$VERSION_FILE already says $VERSION; no bump needed"
else
    ORIGINAL_VERSION_FILE=$(cat "$VERSION_FILE")
    sed -i "s/^__version__ = \".*\"/__version__ = \"$VERSION\"/" "$VERSION_FILE"
    [[ "$(current_version)" == "$VERSION" ]] || die "Failed to update $VERSION_FILE."
    ok "$VERSION_FILE updated ($current -> $VERSION)"
fi

# ---------------------------------------------------------------- 4. test & build

step "Syncing environment"
uv sync --extra dev

step "Running tests"
uv run --extra dev python -m pytest -q

step "Building sdist and wheel"
WORK_DIR=$(mktemp -d)
uv build --out-dir "$WORK_DIR/dist"
ls -1 "$WORK_DIR/dist"

step "Checking package metadata"
uvx twine check --strict "$WORK_DIR"/dist/*

step "Smoke-testing the wheel in a clean venv"
wheel=$(ls "$WORK_DIR"/dist/*.whl | head -n 1)
uv venv --quiet "$WORK_DIR/venv"
if [[ -x "$WORK_DIR/venv/Scripts/python.exe" ]]; then
    venv_python="$WORK_DIR/venv/Scripts/python.exe"
    venv_cli="$WORK_DIR/venv/Scripts/fm-saxml.exe"
else
    venv_python="$WORK_DIR/venv/bin/python"
    venv_cli="$WORK_DIR/venv/bin/fm-saxml"
fi
uv pip install --quiet --python "$venv_python" "$wheel"
reported=$("$venv_cli" --version | tr -d '\r')
[[ "$reported" == *"$VERSION" ]] || die "Installed CLI reports '$reported', expected $VERSION."
ok "fm-saxml --version -> $reported"
FM_SAXML_NO_UPDATE_CHECK=1 "$venv_cli" doctor
ok "fm-saxml doctor passed"

if [[ $DRY_RUN -eq 1 ]]; then
    step "Dry run complete"
    echo "Every check passed for $VERSION. Nothing was committed, tagged or pushed."
    exit 0
fi

# ---------------------------------------------------------------- 5. publish

step "Ready to release $TAG"
echo "  This will:"
[[ "$current" != "$VERSION" ]] && echo "    - commit the version bump on $MAIN_BRANCH"
echo "    - push $MAIN_BRANCH to $REMOTE and wait for CI"
echo "    - create and push tag $TAG, which triggers the Release workflow"
echo "      (executables, GitHub Release and PyPI publish if enabled)"
echo "  ${BOLD}PyPI releases are permanent; $VERSION can never be re-uploaded.${RESET}"
confirm "Proceed?" || die "Aborted. Nothing was pushed."

if [[ "$current" != "$VERSION" ]]; then
    git add "$VERSION_FILE"
    git commit --quiet -m "Version bump to $VERSION"
    BUMP_COMMITTED=1
    ok "committed version bump"
fi

release_sha=$(git rev-parse HEAD)
git push "$REMOTE" "$MAIN_BRANCH"
ok "pushed $MAIN_BRANCH"

# Find the workflow run for a commit; GitHub can take a few seconds to register it.
find_run() {
    local workflow=$1 sha=$2 run_id=""
    for _ in $(seq 1 30); do
        run_id=$(gh run list --workflow "$workflow" --commit "$sha" --limit 1 \
            --json databaseId --jq '.[0].databaseId // empty' 2>/dev/null || true)
        [[ -n "$run_id" ]] && { echo "$run_id"; return 0; }
        sleep 5
    done
    return 1
}

step "Waiting for CI on ${release_sha:0:7}"
ci_run=$(find_run ci.yml "$release_sha") \
    || die "No CI run appeared for ${release_sha:0:7}. Check the Actions tab, then tag manually: git tag -a $TAG -m $TAG && git push $REMOTE $TAG"
if ! gh run watch "$ci_run" --exit-status --interval 15; then
    die "CI failed (run $ci_run). Not tagging. Fix it, then rerun this script with the same version."
fi
ok "CI passed"

step "Tagging $TAG"
git tag -a "$TAG" -m "Release $TAG" "$release_sha"
git push "$REMOTE" "$TAG"
ok "pushed $TAG"

step "Following the Release workflow"
release_run=$(find_run release.yml "$release_sha") \
    || die "No Release run appeared. Check the Actions tab."
if ! gh run watch "$release_run" --exit-status --interval 20; then
    echo
    echo "The Release workflow failed (run $release_run): gh run view $release_run --log-failed"
    echo "If nothing reached PyPI yet, you can delete the tag and retry:"
    echo "  git tag -d $TAG && git push $REMOTE :refs/tags/$TAG"
    exit 1
fi

step "Released $TAG"
gh release view "$TAG" --json url --jq '.url' || true
echo "PyPI: https://pypi.org/project/$PACKAGE/$VERSION/"
echo "(The PyPI job only runs when the PUBLISH_TO_PYPI repo variable is \"true\".)"
