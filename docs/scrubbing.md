# Secret and personal-data scrubbing

Scrubbing is **on by default** for `build`, `parse`, `render` and `diff`. Before any output is written, credentials, tokens and other secrets found in the export are replaced with numbered placeholders. Personal data (emails, card numbers, home-folder usernames) and internal hostnames are kept unless you raise `--scrub-level` to `standard` or `strict`. The calculation logic around them is left intact:

```text
Let ( [ $apikey = "sk-proj-a8Kz9…" ; $url = "https://fms.corp.local/api" ] ; … )
            ↓
Let ( [ $apikey = "[REDACTED:api_key#1]" ; $url = "https://[HOST#1]/api" ] ; … )
```

The same value gets the same placeholder everywhere, so a reader can still tell that two scripts share one key. `Reports/redactions.md` lists every redaction with its location and a masked preview. It never shows the values.

## Options

| Flag | Purpose |
|---|---|
| `--disable-scrubbing` | Turn scrubbing off. Output contains secrets as-is, and the report says so. |
| `--scrub-level secrets\|standard\|strict` | `secrets` (default): credentials only. `standard`: also internal hosts and private IPs, home-folder usernames, emails, card numbers. `strict`: also random-looking string literals and account / modified-by names. |
| `--scrub-keyword WORD` | Treat names containing `WORD` as credentials, in addition to the built-in list (`apikey`, `token`, `password`, `secret`, …). Repeatable. |
| `--scrub-allow REGEX` | Never redact values matching `REGEX`. Repeatable. |
| `--fail-on-secrets` | Exit with status 1 (after writing everything) if the export contains hardcoded credentials. For CI. |

`strict` also covers phone numbers, IBANs (checksum-verified) and US SSN / Canadian SIN numbers.

## Allowing a calculation

A comment containing `fm-saxml:allow` leaves that calculation exactly as written. For example, write `/* fm-saxml:allow: public sandbox key */` above a documented test key. Values in an allowed calculation are allowed everywhere, so the same key isn't redacted next door. Allowed items are listed in the report.

## Stable placeholders across runs

Placeholders are numbered per run (`#1`, `#2`), so two separately saved `model.json` files can't be compared value by value, and `diff` warns about this. Set `FM_SAXML_SCRUB_SALT` to a private value of at least 16 characters to get keyed fingerprints instead (`[REDACTED:password#3f9a1c]`). These are the same for the same value in every run that uses the salt. Keep the salt private: anyone holding it can test guesses against a fingerprint.

## Scrubbing the XML itself (`scrub`)

```bash
fm-saxml scrub MySolution.xml                       # writes MySolution.scrubbed.xml
fm-saxml scrub MySolution.xml -o share.xml --report share.redactions.md
```

`scrub` writes a redacted copy of a Save a Copy as XML export, for sharing the raw XML with an AI tool or another developer. It applies everything `build` would redact to every copy of each value: the calculation, its tokenized ChunkList, and the rendered step text in `DDR_INFO`.

- It removes the `hash` attributes of changed elements, since a digest of the original content could be used to confirm a guessed password.
- Binary streams are left untouched.
- The output is the input file with only those spans patched: same encoding (including UTF-16 and its BOM), declaration, line endings and formatting. A diff between the two shows exactly what was redacted.
- It accepts only `FMSaveAsXML` exports. Clipboard XML (`fmxmlsnippet`) and DDR reports (`FMPReport`) are refused, because they lay out step parameters differently.

## What is detected

- Provider key formats (OpenAI, Anthropic, Google, AWS, GitHub, GitLab, Slack, Stripe, SendGrid, OttoFMS, JWTs, webhook URLs, …).
- `keyword = "value"` assignments, including inside commented-out code.
- JSON bodies, HTTP headers, cURL `-u`, URL passwords and secret query parameters, and connection strings.
- Base64 `user:password` values, and every literal in a private-key calculation.
- By position in the script:
  - password parameters (Re-Login, Reset Account Password, …) and Configure AI / RAG Account;
  - Set Variable into a credential-named variable, and Set Field into a credential-named field;
  - JSONSetElement credential keys, Crypt* keys, MBS credential calls and plugin licence registration.

  A secret passed as a `$variable` is traced back to the Set Variable that assigned it and redacted there.
- Credentials written as prose in comments ("temp password is swordfish99").

Some things are **flagged for review** instead of changed, in a "Needs review" section of the report:

- a credential read from a field (nothing in the file to redact);
- a variable whose source couldn't be found;
- a plain word stated as a password in a comment.

Only string literals and comments are ever changed. After writing, a guard searches every output file for each redacted value. If one survived somewhere the scrubber doesn't look (for example, a script *named* after a password), the run fails with exit code 2.

This is a heuristic scrubber, not a guarantee: review output before sharing it. Detection rules are adapted from Andrew Kear's [FileMaker XML Scrubber](https://github.com/andykear/FileMaker-XML-scrubber) (Clockwork Creative Technology, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)). The design and roadmap are in [secret-redaction.md](../secret-redaction.md).
