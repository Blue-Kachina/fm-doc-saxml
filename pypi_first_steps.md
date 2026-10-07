# Publishing fm-saxml-converter to PyPI — first-time guide

Everything that can be automated already is. What's left are the one-time account
and settings steps that only you can do, then a tag push to release.

**What's already in the repo**

- `LICENSE` (MIT) and full package metadata in `pyproject.toml`
- Single source of truth for the version: `__version__` in `src/fm_saxml/__init__.py`
- `.github/workflows/ci.yml` — tests on Windows/macOS/Linux × Python 3.11–3.13
- `.github/workflows/release.yml` — on a `v*` tag: checks the tag matches the version,
  builds standalone executables for GitHub Releases, then publishes to PyPI using
  **Trusted Publishing** (no password or API token is stored anywhere)
- `fm-saxml --version` and a once-a-day "newer version available" notice for users

**Not yet verified:** the two workflows have never run on GitHub, so the first push is
the real test. The Windows executable and the package build were tested locally.

---

## Step 1 — Make sure the code is on GitHub

The workflows only run on GitHub, so the repository must be pushed with the `.github/`
folder committed.

1. Commit the work. Review `git status` first. It includes your parser/template edits
   and the untracked `calc_refs.py` and `chunk_lists.py`, which the code needs.
2. Push to `https://github.com/Blue-Kachina/fm-doc-saxml` (the URL used in
   `pyproject.toml` and `version.py`; change both if the repo lives elsewhere).
3. Open the repo's **Actions** tab and wait for **CI** to go green on all three
   operating systems. Fix anything that fails before continuing. This is the first time
   the tests run on macOS and Linux.

## Step 2 — Create your PyPI accounts

1. Register at <https://pypi.org/account/register/>.
2. **Turn on two-factor authentication** (required to publish). Use an authenticator
   app, and save the recovery codes somewhere safe.
3. Optional but recommended: register separately at <https://test.pypi.org/> (a sandbox
   with its own accounts) so you can rehearse. See Step 6.

## Step 3 — Check the package name

Visit <https://pypi.org/project/fm-saxml-converter/>.

- **404 Not Found** → the name is free. Continue.
- **A project page appears** → the name is taken. Pick a new `name` in `pyproject.toml`
  (the command stays `fm-saxml`), and use the new name everywhere below and in the README.

## Step 4 — Register a "pending" Trusted Publisher on PyPI

This lets GitHub publish for you without a stored token, **and it works before the
project exists**, so no manual first upload is needed.

1. Log in to PyPI → your account menu → **Your projects** → **Publishing**
   (<https://pypi.org/manage/account/publishing/>).
2. Under **Add a new pending publisher**, choose the **GitHub** tab and enter exactly:

   | Field | Value |
   |---|---|
   | PyPI project name | `fm-saxml-converter` |
   | Owner | `Blue-Kachina` |
   | Repository name | `fm-doc-saxml` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

3. Save. The first successful publish from that workflow creates the project and
   converts this into a normal trusted publisher.

These five values must match the workflow exactly. A typo or a case difference is the
most common reason publishing fails with an `invalid-publisher` error.

## Step 5 — Configure GitHub

In the GitHub repo → **Settings**:

1. **Environments → New environment**, named exactly `pypi`.
   Recommended: tick **Required reviewers** and add yourself. Each PyPI publish then
   waits for your click, so a stray tag can't publish by accident.
2. **Secrets and variables → Actions → Variables tab → New repository variable**:
   name `PUBLISH_TO_PYPI`, value `true`. Without it the workflow builds the executables
   but skips PyPI, a handy safety switch.

## Step 6 — (Optional) Rehearse locally

Check that the package builds and its README renders properly on PyPI:

```bash
uv build
uvx twine check dist/*
```

Both should say `PASSED`. To rehearse the upload itself, create an API token on
TestPyPI (Account settings → API tokens), then:

```bash
uv publish --publish-url https://test.pypi.org/legacy/ --token <testpypi-token>
```

Versions uploaded to TestPyPI don't count against real PyPI. To test-install it:

```bash
pipx install --index-url https://test.pypi.org/simple/ --pip-args="--extra-index-url https://pypi.org/simple/" fm-saxml-converter
```

(The extra index is needed because dependencies like `lxml` live on real PyPI.)

## Step 7 — Release

The version is currently `0.1.0`, so you can release it as is.

```bash
git tag v0.1.0
git push origin v0.1.0
```

Then watch the **Actions** tab. The `Release` workflow runs:

1. **verify** — fails if the tag doesn't match `__version__` (so `v0.1.0` ↔ `0.1.0`).
2. **executables** — builds Windows, macOS and Linux executables, smoke-tests each
   with `doctor`, and attaches them to a new GitHub Release.
3. **pypi** — publishes to PyPI. If you enabled required reviewers, approve it when
   prompted.

The `pypi` job only runs if the executables succeeded. If one OS fails, fix it, then
either re-run the failed jobs (if the fix was a workflow/settings change) or delete the
tag (`git tag -d v0.1.0 && git push origin :refs/tags/v0.1.0`) and re-tag. Deleting a tag
is safe as long as nothing was published yet.

## Step 8 — Verify

1. Open <https://pypi.org/project/fm-saxml-converter/>. Check the description (it comes
   from the README), the MIT license and the links.
2. In a clean terminal:

   ```bash
   pipx install fm-saxml-converter
   fm-saxml --version
   fm-saxml doctor
   ```

3. Download one executable from the GitHub Release and run `doctor` on it.

---

## Later releases

1. Change `__version__` in `src/fm_saxml/__init__.py` (the only place).
2. Commit and push; wait for CI to pass.
3. `git tag vX.Y.Z && git push origin vX.Y.Z`.

Version numbers follow `MAJOR.MINOR.PATCH`: bump PATCH for fixes, MINOR for new
features, MAJOR for breaking changes. While you're on `0.x`, the tool is understood to
still be settling.

**Releases are permanent.** PyPI never lets you replace or re-upload a version number.
If a release is bad, publish a new version. You can *yank* a release (PyPI project page →
Manage → Releases) so installers skip it, but the number can't be reused.

### How users update

| Installed with | Update command |
|---|---|
| `pipx` | `pipx upgrade fm-saxml-converter` |
| `uv tool install` | `uv tool upgrade fm-saxml-converter` |
| `pip` | `pip install -U fm-saxml-converter` |
| `uvx` | `uvx --from fm-saxml-converter@latest fm-saxml ...` |
| Executable | Download the new file from GitHub Releases |

Nothing updates automatically. Users do see a one-line notice after a run when a newer
version exists. The check happens at most once a day, never blocks, and is silent in
CI, when output is piped, or when `FM_SAXML_NO_UPDATE_CHECK=1` is set. The notice only
starts working once a newer version than theirs is on PyPI.

---

## Things to know about the executables

- **Windows** may show a SmartScreen "unrecognized app" warning (click *More info →
  Run anyway*), and **macOS** may block the file as from an "unidentified developer"
  (right-click → *Open*, or run `xattr -d com.apple.quarantine fm-saxml-macos`). Removing
  these warnings requires paid code-signing certificates. It's optional and can wait
  until there are real users asking.
- The macOS build is Apple Silicon (arm64) only, because `macos-latest` runners are arm64.
  Intel Mac users can use the PyPI install.
- On macOS/Linux a downloaded file may need `chmod +x fm-saxml-macos` before it runs.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `invalid-publisher` / "no trusted publisher matches" | One of the five values in Step 4 doesn't exactly match (owner, repo, `release.yml`, `pypi`), or the job isn't using `environment: pypi`. |
| `403` / "name already taken" | Someone else owns the name. See Step 3. |
| `File already exists` | That version was already uploaded. Bump the version and re-tag. |
| `verify` job fails | The tag doesn't match `__version__`. Fix the version or the tag. |
| `pypi` job skipped | `PUBLISH_TO_PYPI` isn't set to `true`, or an earlier job failed. |
| README renders as plain text on PyPI | Run `uvx twine check dist/*` and fix what it reports. |
| macOS/Linux CI failures on first push | Expected possibility. Platform issues the Windows-only test runs couldn't reveal. Fix and push again. |

## Fallback: publish by hand with an API token

If Trusted Publishing gives you trouble, you can publish from your machine. Create a
token at PyPI → Account settings → API tokens (first upload: scope "Entire account";
afterwards, scope it to this project), then:

```bash
uv build
uv publish --token <pypi-token>
```

Treat the token like a password and never commit it.
