# Secret and PII Redaction

Plan for keeping credentials, tokens, internal hostnames and personal data out of everything `fm-saxml` writes: Markdown, `entities.json` / `references.json` / `backlinks.json`, `external-references.json`, `model.json` and diff reports.

The approach is adapted from Andrew Kear's [FileMaker XML Scrubber](https://github.com/andykear/FileMaker-XML-scrubber) (v1.4, CC BY 4.0), a single-file browser tool that redacts FileMaker XML before it is shared with AI tools.

Status: **Phases 1–3 implemented** (`src/fm_saxml/scrub/`, on by default, `--disable-scrubbing` to opt out). §6 describes what was built; where the build differs from the original proposal, it says so.

---

## 1. Goal

`fm-saxml` output is made to be read: pasted into an LLM, committed to a repo, attached to a ticket. Today every calculation, step parameter, comment and value list is copied verbatim into that output. Any API key, password, bearer token or internal hostname hardcoded in the solution goes with it.

**Goals**

- Redact secrets **by default** in every output artifact, while keeping the calculation logic readable (`$apikey = "[REDACTED]"`, not a deleted line).
- Redact personal data (emails, card numbers, home-directory usernames) at a configurable level.
- Produce a findings report that says *what* was redacted and *where*, without repeating the value.
- Make leaks fail loudly: a final guard scans the written files for any value the engine redacted.

**Non-goals**

- A guarantee. This is a heuristic scrubber, like the original. The docs and the CLI summary have to say so.
- Redacting schema: table, field, layout, script and privilege set names stay. They are what the documentation is about.
- Reading record data. SaveAsXML carries design, not data, apart from value lists and literal text.

---

## 2. What the Clockwork scrubber does

Input: DDR XML, Save-as-XML, clipboard `fmxmlsnippet`, custom function XML. Output: the same XML with secrets replaced by `[REDACTED]`, `[HOST]`, `[USER]`, `[EMAIL]` or `[CARD]`, plus a findings list. It runs entirely in the browser.

What it catches falls into four groups.

### 2.1 Known key formats (shape-based, matched everywhere, comments included)

These have near-zero false positives, so the whole string literal is replaced wherever one appears.

| Provider | Pattern (simplified) |
|---|---|
| OpenAI / Anthropic | `sk-proj-…`, `sk-…` (covers `sk-ant-`) |
| Google | `AIza…` |
| xAI, Groq | `xai-…`, `gsk_…` |
| AWS key ID | `AKIA` / `ASIA` + 16 |
| GitHub | `gh[posru]_…`, `github_pat_…` |
| Slack | `xox[baprs]-…` |
| Stripe | `[sr]k_(live\|test)_…` |
| SendGrid | `SG.xxx.xxx` |
| OttoFMS | `dk_…` (Data API), `ak_…` (Admin API) |
| JWT | `eyJ….….…` |
| PEM / SSH | `-----BEGIN … PRIVATE KEY-----`. When this marker is present, every literal in the calc is redacted, so keys split across `&` concatenations are covered. |
| Webhook URLs | Slack, Discord, Teams/Power Automate (the URL is the credential) |

### 2.2 Contextual redaction (identified by name or position, code only, comments skipped)

- **Keyword assignments** in calc text: `$apikey = "…"`, Let() locals without `$`, matched against a keyword list (api key, token, bearer, authorization, password, secret, smtp pass/key, private/auth/ssh key, sftp pass, passphrase, credential, oauth, plus user keywords).
- **JSON bodies**: `"password":"…"`, and the escaped `\"password\":\"…\"` form used in Insert from URL `--data` strings.
- **Credential-named variables**: a Set Variable (step 141) whose *name* matches a keyword has its literal(s) redacted, whatever the value looks like.
- **Credential-named elements**: `<Password>` and similar in Re-Login, Add Account, Reset/Change Password, Send Mail SMTP and ODBC steps. Account names are kept.
- **Credential-named targets**: Set Field / Insert Text / Set Field By Name into a field like `Users::Password`.
- **Positional credential arguments**, with three-way handling:
  - `JSONSetElement` key/value pairs (flat and `[key;value;type]` forms) where the key is credential-named.
  - `CryptEncrypt` / `CryptDecrypt` (and the Base64 variants) argument 2, `CryptAuthCode` argument 3.
  - MBS `CURL.SetOptionPassword` / `SetOptionUserName` / `SetOptionXOAuth2Bearer`.
  - Plugin licences: `MBS("Register"; …)`, `*_Register(…)`.
  - A **literal** argument is redacted in place. A **`$variable`** is traced back to the nearest earlier Set Variable in the same script and redacted there. A **field reference** is flagged, since the secret lives in data.
- **HTTP headers** anywhere in text: `Authorization: Bearer|Basic|Token|Digest|OAuth …`, `X-API-Key`, `Ocp-Apim-Subscription-Key`, `Cookie` / `Set-Cookie`, cURL `-u user:pass`.
- **URLs**: `scheme://user:password@host` (password removed, user kept), and secret query parameters (`api_key`, `token`, `access_token`, `secret`, `sig`, `sas`, `code`, `key`, session ids…).
- **Connection strings**: `password=` / `pwd=` / `AccessToken=` / Azure `AccountKey=` and `SharedAccessSignature=` in data-source attributes.
- **Base64 `user:pass`**: base64-looking runs in literals are decoded. A printable `user:password` result is redacted. Results starting with `{` or `<` (JWT segments, payloads) are skipped.
- **Configure AI Account** (step 212): every calc is redacted.
- **Internal hosts**: private IPv4 ranges, single-label hosts, and `.local/.internal/.lan/.corp/…` TLDs become `[HOST]`, across `http(s)`, `ftp`, `sftp`, `smb`, `ldap`, `fmp://`, `fmnet:/`, `filewin:`/`filemac:` and UNC `\\SERVER\share`. Public hosts are left alone.
- **Home directories**: `/Users/jsmith/`, `/home/jsmith/`, `C:\Users\jsmith\` become `[USER]`.
- **Attributes** whose name matches a keyword.

### 2.3 Flag only, never modified

- Comments where a credential keyword is followed by a value (`temp password is hunter2`). Redacting prose is too destructive, so these go to manual review.
- Unresolved variable traces and field-reference credentials.

### 2.4 Personal data (off by default there)

- Emails become `[EMAIL]`. Card numbers become `[CARD]`: 13–19 digits that pass the Luhn check, which keeps FileMaker's long ids out.

---

## 3. How it does it

The engine is about 600 lines of JavaScript in `clockwork-scrubber.html`. The design choices worth keeping:

1. **DOM, not text.** The file is parsed with `DOMParser`, passes run over the tree using CSS selectors (`Step[id="141"]`, `Value > Calculation`), and the result is serialized back. Calc text is written back into CDATA, so `<`, `>` and `&` are not re-escaped.
2. **Ordered passes with a `done` set.** The most specific rules run first: AI account, credential-named variables, elements and targets, PEM, plugin register, CURL, native functions. Each marks the calc node it rewrote. The generic pass (known keys, keyword assignments, headers, URLs, hosts) then skips those nodes, so nothing is redacted or counted twice. Plugin-register redaction deliberately does *not* mark the node, so a real key elsewhere in the same calc is still caught.
3. **Code vs. comment spans.** `splitComments()` is a small state machine that splits calc text into code and `/* */` / `//` comment spans and ignores markers inside string literals. Keyword and host passes only touch code spans. Known-key shapes are matched across both.
4. **Balanced-paren argument walking.** `splitTopLevelArgs()` and the paren walkers find a call's arguments while respecting nested calls and string literals. This is how positional credentials are found without a full parser.
5. **Idempotence guards.** Every replacement callback returns early when the value is already `[REDACTED]`, so overlapping passes don't stack.
6. **Findings come from the redactions.** Each rewrite pushes a finding (severity, kind, category, location, count, masked preview, note). The on-screen count and the downloaded file can't disagree. Previews are built from the *redacted* text, as short windows around each marker.
7. **CDATA repair.** FileMaker sometimes writes `]]>` inside calc text. Four escalating repair passes run until the parser accepts the file.

Its limits, which our version can fix (§5): regex scanning over raw text, `'…'` treated as a string (FileMaker strings are double-quoted only), variable tracing limited to one script, a single `[REDACTED]` token for every value, and no check that the output is actually clean.

---

## 4. A Python equivalent

Almost everything ports directly. We already depend on `lxml`, and the regexes translate nearly 1:1.

| JS construct | Python equivalent | Notes |
|---|---|---|
| `DOMParser` + selectors | `lxml.etree` + our `_helpers.find_*` / XPath | Already the parser's foundation. |
| `RegExp` with callbacks | `re.compile(...).sub(fn, s)` | Python allows lookbehind, so the card-number capture workaround isn't needed. |
| `atob` | `base64.b64decode(tok, validate=True)` + `.decode("ascii")` | Catch `binascii.Error` / `UnicodeDecodeError`. |
| `splitComments`, `splitTopLevelArgs`, paren walkers | One **FileMaker calc lexer** (§5.1) | Replaces three ad-hoc scanners. |
| `done` Set of nodes | `set[int]` of `id()`s, or a per-string "owned" flag | |
| `changes[]` findings | `Finding` dataclass → `RedactionReport` | Rendered to Markdown + JSON. |
| CDATA repair | `etree.XMLParser(recover=True, strip_cdata=False, huge_tree=True)` | Only needed for the XML-out mode (§6.7). |

**Where it runs differs, and that matters.** The original rewrites XML. We don't emit XML. We parse into a `RawModel`, normalize into a `DocumentModel`, and render from that. So the Python version works on **our model's strings**, with the structural context (step type, variable name, target field, parameter type) that SaveAsXML already gives us in typed form:

- Set Variable in SaveAsXML v2 is `<Step id="141" name="Set Variable">` → `<ParameterValues><Parameter type="Variable"><value><Calculation>…` with the variable name in `<Name value="$x"/>` (an attribute, not element text as in `fmxmlsnippet`).
- v2 calcs come with a **ChunkList** in `DDR_INFO` that already tokenizes them (`NoRef`, `FieldRef`, `VariableReference`, `CustomFunctionRef`, …). We extract it for references today in `parser/extractors/chunk_lists.py`.
- The same calc text exists in several places in the XML (calc `<Text>`, ChunkList chunks, `DDR_INFO` StepText) and in several fields of our model (`calculation`, `calculations[].text`, and `raw_text`, which embeds the first 80 characters of the calc).

That last point is the main trap: a pass that only cleans `calculation` will leave the key in `raw_text`. Truncation can also cut a key below the regex's minimum length, so the shape pass would no longer match the leaked prefix.

---

## 5. Improvements over the original

### 5.1 A real calc lexer instead of regexes over raw text

`redact/calc_lexer.py`: a small tokenizer for FileMaker calculation syntax that emits typed tokens with source spans:

`STRING` (double-quoted, `\"` and `\\` escapes, `¶`) · `COMMENT_BLOCK` · `COMMENT_LINE` · `VAR` (`$x`, `$$x`, `~x` Let locals) · `FIELD` (`TO::Field`) · `IDENT` / `FUNC` · `LPAREN` `RPAREN` `LBRACK` `RBRACK` `SEMI` · `OP` · `NUMBER` · `WS`

Every detector then works on tokens: "string literal on the right of `=` whose left identifier matches a keyword", "argument 2 of call `CryptEncrypt`", "STRING tokens in a calc that contains a PEM marker". Replacement is span-based and applied right to left, so rules can't overlap or corrupt each other, and **only `STRING` and `COMMENT` contents can ever change**. That invariant is directly testable (§6.8). It also fixes the original's single-quote handling and its square-bracket blind spot (`JSONSetElement` groups, `Let([ … ])`).

When a v2 ChunkList is available, it can cross-check the lexer, for example to confirm that a `$name` is a `VariableReference`.

### 5.2 Use the typed SaveAsXML structure

The parser already knows step type ids, parameter types (`Variable`, `Calculation`, `Field`, `Target`, …) and target field references. Contextual rules key on those instead of selector guesses:

- Set Variable: `Parameter[@type="Variable"]/Name/@value`.
- Set Field / Insert Text / Insert Calculated Result: the target `FieldReference` name.
- Re-Login, Add Account, Reset/Change Account Password, Send Mail (SMTP), Configure AI Account, Insert from URL (cURL options): identified by step id **and** name.

**Format note.** Step type ids are FileMaker's own identifiers and are the same in clipboard XML (`fmxmlsnippet`), DDR (`FMPReport`) and SaveAsXML (`FMSaveAsXML`). The formats differ in how a step's *parameters* are written:

| | Clipboard | DDR | SaveAsXML |
|---|---|---|---|
| Set Variable name | `<Name>$x</Name>` | similar named children | `<Parameter type="Variable"><Name value="$x"/>` |
| A password | `<Password><Calculation>…` | similar named children | `<Parameter type="Password"><Calculation><Calculation><Text>…` |
| Calc text | `<Calculation><![CDATA[…]]>` | `<Calculation>` + `<StepText>` | nested `<Calculation><Calculation><Text>`, plus ChunkList / StepText copies in `DDR_INFO` |

The scrubber's selectors (`<Password>` elements, `<Name>` text, `Value > Calculation`) are clipboard/DDR shapes and match nothing in SaveAsXML. They were rebuilt here on SaveAsXML's typed parameters. The ids in the scrubber's test corpus (Re-Login `72`, Add Account `137`) are simply inaccurate: real exports have Re-Login `138` and Add Account `134`. Its engine never keys on those two ids, so the error was never exercised. Our parser's "v1" path and its fixtures are hand-written, clipboard-like shapes that haven't been checked against a real early SaveAsXML export, so the structural rules target the verified v2 shapes only.

### 5.3 File-wide variable tracing

The original traces `$var` only within the current script and flags `$$globals` as unresolved. We have the whole file in memory, so we can:

1. Trace `$var` within the script (same as the original), including through `Let()` locals in the same calc.
2. Trace `$$var` across **every** script in the file and redact every literal assignment of it.
3. Flag (not trace) values that arrive via `Get(ScriptParameter)` / `Get(ScriptResult)`, naming the calling scripts we already know from references.

### 5.4 Stable, numbered placeholders

`[REDACTED]` everywhere loses information an LLM reader can use. Proposal: `[REDACTED:api_key#1]`, `[REDACTED:password#2]`, numbered by **distinct value** within a run. The same secret used in five scripts gets the same label, so "these two calls use the same key" survives redaction while the value doesn't. Hosts get the same treatment: `[HOST#1]`.

For `diff` stability across runs (§6.6), the label can optionally come from a keyed hash, `HMAC-SHA256(salt, value)[:6]`, with the salt from `FM_SAXML_SCRUB_SALT` (implemented in Phase 3). Without a salt, a short unkeyed hash of a weak password could be brute-forced, so numbering stays the default.

### 5.5 Global value substitution

Once a detector identifies a secret value, that exact value is replaced **everywhere** in the model, not just at the site where it was detected. If `"hunter2"` is detected as a Re-Login password, a copy of it in a comment, a `raw_text` preview or a custom function also goes. This is cheap: one combined, length-sorted `re.escape` alternation over all strings. Values shorter than 4 characters are excluded to avoid replacing things like `"1"`.

### 5.6 An exact-value output guard

After rendering, scan every written file for each redacted value (and its JSON-escaped and HTML-escaped forms). Any hit is a pass we missed, so the run **fails**: exit code 2, with the file and line, and the value masked in the message. This is the defense-in-depth layer the original lacks, and it is only possible because the engine knows exactly what it redacted. A second, cheaper guard runs the known-key shapes (§2.1) over the output and warns on anything new.

### 5.7 More detectors

- Additional provider shapes (compare with the gitleaks rule set, MIT licensed): Google OAuth client secrets `GOCSPX-…`, GitLab `glpat-…`, Hugging Face `hf_…`, Shopify `shpat_…`, npm `npm_…`, Slack app `xapp-…`, Twilio API key `SK` + 32 hex, Mailgun `key-…`, and Google service-account JSON (`"private_key":`).
- FileMaker-specific: Data API session tokens in `X-FM-Data-Session-Token` headers, `fmrest` / `fmp://` URLs that carry `?password=`, Claris Connect / FM Cloud refresh tokens in Insert from URL headers.
- **Entropy check (strict level)**: string literals of 20+ characters with Shannon entropy above about 4.0 bits/char, no spaces, and not a UUID or hex hash we generated ourselves. Flagged at `standard`, redacted at `strict`.
- **More PII (strict level)**: phone numbers (E.164 and NANP shapes), IBAN (mod-97 check), US SSN / Canadian SIN (Luhn), IPv6 ULA/link-local, and account names from the Accounts catalog.

### 5.8 Allowlisting and suppression

- `--redact-allow REGEX` (repeatable) for values that are known to be safe.
- An inline marker in a calc comment, `/* fm-saxml:allow */`, skips the calc it appears in and records an "allowed" finding.
- Custom keywords: `--redact-keyword WORD` (the original's "custom patterns").

### 5.9 Reporting that can't leak

The report lists category, detector id, location (as a link to the entity's page), count and a masked preview window. It never includes the value. An optional `--show-redaction-hashes` adds the salted fingerprint for auditing.

---

## 6. Integration plan

### 6.1 Where it runs in the pipeline

```
parse_savexml ──► Scrubber.scrub_raw ──► normalize ──► resolve_references ──► backlinks ──► warnings ──► validate
                  (pass 1: detect,                                                                     │
                   pass 2: substitute)                                                                 ▼
                                                     render (md / json / model.json / diff report)
                                                                                                       │
                                                                                                       ▼
                                                                                              guard_output
```

1. **`Scrubber.scrub_raw(raw) -> ScrubSummary`**, right after parsing. It runs before normalize, so every downstream copy (normalized entities, `references`, `warnings`, backlinks) is built from clean text. Pass 1 detects and replaces. Pass 2 is the global value substitution from §5.5. It then re-derives step `raw_text` from the scrubbed calc, which fixes the truncated-copy trap from §4. The source file path is scrubbed too (home-folder usernames).
2. **No separate `sweep_model`.** The proposal had a second sweep over the `DocumentModel`. Every model string comes from the scrubbed raw records, so the guard covers anything that slips past instead.
3. **`guard_output(target, values)`**, after all files are written (§5.6). Exit code 2 on a hit.

`_run_pipeline` in `cli.py` has a "Scrubbing secrets" progress step between parsing and normalizing. Measured cost: about 0.5 s on the 32 MB `NEXUS_saxml.xml` export, out of a 90 s build.

The calc references we derive from text (`normalize/calc_refs.py`) aren't affected: literals hold no field, layout or script references, and the lexer guarantees only `STRING` and `COMMENT` contents change.

### 6.2 Module layout

As built (Phase 1):

```
src/fm_saxml/scrub/
  __init__.py          # Scrubber, ScrubPolicy, ScrubLevel, guard_output, attribution
  calc_lexer.py        # lossless FileMaker calc tokenizer (§5.1)
  policy.py            # levels, credential keywords, non-secret name suffixes, allowlist
  placeholders.py      # numbered labels, shared registry, "safe to substitute" rule (§5.4)
  walker.py            # which model strings are calc / text / person / skipped; step raw_text rebuild
  engine.py            # Scrubber: detection, overlap resolution, two passes, findings
  guard.py             # exact-value scan of written files (§5.6)
  detectors/
    __init__.py        # Hit, regex helper, detectors enabled per level
    known_keys.py      # provider shape registry + PEM marker
    credentials.py     # JSON keys, HTTP headers, cURL -u, URL userinfo / query params, connection strings
    encoded.py         # base64 user:pass
    hosts.py           # private IPs, internal hosts in URLs / UNC / bare FQDNs, home-dir usernames
    pii.py             # email, Luhn cards
    entropy.py         # high-entropy literals (strict)
```

Added in Phase 2:

```
  structural.py        # planner: structural rules + $var / $$var tracing, run before pass 1
  positional.py        # call parser + registry: JSONSetElement, Crypt*, MBS selectors, *_Register
  detectors/comments.py  # credentials written as prose
```

Step context lives in `walker.StepCtx` rather than a separate `context.py`, and tracing lives in the planner rather than a separate `tracing.py`. The planner runs on the original texts and returns hits keyed by slot, so a variable used in step 40 can be redacted at its Set Variable in step 12.

Detectors are plain functions `detect(text, policy) -> Iterable[Hit]`, where `Hit` is a span plus category, detector id and priority. In calc text, the engine runs them over the whole calc and keeps only hits that fall entirely inside one string literal or comment. Token rules (keyword assignment, PEM, entropy) work on the lexer's token stream. Overlaps are resolved by priority: the most specific detector wins, the same idea as the original's pass order. Each provider shape is a registry row, so adding one is a one-line change plus a test.

Rather than an allowlist of keys to scan, the walker uses a **denylist** of identifier, name and enum keys (`*_id`, `uuid`, `name`, `*_name`, `type`, …). Any other string is scanned. A new extractor field is scanned by default rather than leaked.

### 6.3 What gets scanned

| Source in the model | Treatment |
|---|---|
| Field calcs (formula, auto-enter, validation), step calcs, custom function bodies, layout object calcs (hide, tooltip, conditional formatting, web viewer, button), script trigger params, custom menu calcs | Full calc pipeline (lexer + all detectors). |
| Step params that aren't calcs (Insert Text `<Text>`, Send Mail fields, Insert from URL options) | String detectors + structural rules. |
| Comments (field, script step, table, layout object) | Known-key shapes + PII redact. Keyword prose is flag-only. |
| Value list custom values, layout text objects (`raw_text`) | Known-key shapes, hosts, PII. |
| External data source and file reference paths | Hosts, userinfo passwords, home-dir usernames. |
| Accounts catalog, modified-by names | Kept at `standard`, `[PERSON#n]` at `strict` (built-in `[Guest]`-style names and directory-group UUIDs are kept). Passwords never appear in SaveAsXML. |
| Attributes captured into raw dicts | Credential-named attribute rule. |

### 6.4 CLI surface

Applies to `build`, `parse`, `render` and `diff`.

| Option | Default | Meaning | Status |
|---|---|---|---|
| `--disable-scrubbing` | off | Turn scrubbing off entirely. | done |
| `--scrub-level [secrets\|standard\|strict]` | `standard` | `secrets`: credentials only. `standard`: plus hosts, home-dir users, emails, cards. `strict`: plus high-entropy literals and account / modified-by names. | done (phone/IBAN/SSN still to come) |
| `--scrub-keyword WORD` | – | Extra credential keyword (repeatable). | done |
| `--scrub-allow REGEX` | – | Never redact values that fully match (repeatable). Also silences the guard for them. | done |
| `--fail-on-secrets` | off | Exit 1 (after writing everything) if a hardcoded credential was redacted or flagged. Hosts and personal data don't count. For CI. Renamed from the proposed `--fail-on-redaction`. | done |

The flags use "scrub" rather than the proposal's "redact", to match `--disable-scrubbing`. `inspect` and `validate` always scrub at `standard`, since they only print.

`--disable-scrubbing` prints a red warning, records `scrubbing: {"applied": false}` in the model, and makes `Reports/redactions.md` and `Reports/summary.md` say the output is unredacted. The guard (exit 2) only runs when scrubbing is on.

The end-of-run summary prints a line like `Scrubbed 9 value(s) in 15 place(s) (7 email, 1 token, 1 user). See Reports/redactions.md.` The report is always written: Markdown in `Reports/redactions.md`, and the findings are also in `model.json` under `scrubbing`.

A config file (`[tool.fm-saxml.redact]` in `pyproject.toml`, or `fm-saxml.toml`) waits for the general config work that is already deferred. The flags above cover Phase 1–2.

### 6.5 Model metadata

`DocumentModel.scrubbing` (`ScrubSummary`): `applied`, `level`, `engineVersion`, distinct-value `counts` by category, and `findings` (placeholder, category, detector, location, masked preview). Then:

- `render` (and `diff` with a `model.json` input) scrubs the loaded model with the current engine if it wasn't scrubbed, or was scrubbed by an older engine version. A `model.json` from an older release can't be rendered unredacted by accident.
- `SCHEMA_VERSION` went from 0.1.0 to 0.2.0.

### 6.6 `diff`

As built: both sides are scrubbed by **one `Scrubber`** with a shared placeholder registry, and the diff runs on the scrubbed models. A value present on both sides gets the same placeholder, so it doesn't show as a change. A changed API key shows as `[REDACTED:api_key#1] → [REDACTED:api_key#2]`. The change is visible without either value, which is what the proposal wanted, but without diffing unredacted models first. The guard then runs on the report.

When either side is a `model.json` scrubbed in an earlier run, numbered labels came from a different registry, and `diff` warns that redacted values can't be compared. With `FM_SAXML_SCRUB_SALT` set to the same value for every run, labels are keyed fingerprints. `ScrubSummary` records `placeholderStyle` and a `saltId`, which identifies the salt without revealing it, and `diff` stays quiet when both sides match.

### 6.7 `fm-saxml scrub` (built in Phase 3)

`fm-saxml scrub in.xml [-o out.xml] [--report r.md]` writes a redacted Save a Copy as XML for sharing the raw XML (`scrub/xml_writer.py`).

1. **Same rules as `build`.** The export is parsed and scrubbed by the normal model pass, so structural rules and tracing apply. The scrubber reports every string it changed (`Scrubber.last_changes`).
2. **Every copy.** Each text node and attribute of the source tree gets, in order:
   - the scrubbed version, on an exact match (a calc's `<Text>`, a comment, a value);
   - otherwise each changed literal or comment *token*, which covers ChunkList chunks and StepText in `DDR_INFO`, including short values too risky to substitute everywhere;
   - otherwise known-value substitution, plus the detectors for content the parser doesn't extract (comment steps, step text, Import Records file paths).

   Substitution repeats until no new value appears, so a value first seen late in the file is also replaced earlier in it. Binary `<Stream type="Hex">` data is never touched.
3. **Hashes.** `hash` attributes are removed from changed elements and their ancestors, from the DDR_INFO entries, and from the `DDRREF`s pointing at them. A content digest of the original would let someone confirm a guessed weak password offline.
4. **Byte-preserving output.**
   - Elements are located by document order. libxml2's `sourceline` stops at 65535, which real exports exceed.
   - Each value is decoded with a position map (entities, CDATA, CR / CRLF normalization), and only the changed tokens are spliced back, escaped like their surroundings.
   - The result keeps encoding, BOM, declaration, line endings, CDATA and entity style. On disRenewalUniverse (20 MB) the diff is 37 changed lines; on NEXUS (32 MB), 125.
   - If any patch can't be placed and verified exactly, the document is re-serialized instead (equivalent XML) and the user is told.
5. **Checks.** The guard runs on the output (UTF-16 aware). Re-scrubbing a scrubbed export is byte-identical, and `build` works on a scrubbed export.

Only `FMSaveAsXML` is accepted. `fmxmlsnippet` and `FMPReport` are refused with a message naming the format (see the format note in §5.2).

### 6.8 Testing

- **Port the scrubber's corpus** (`scrubber-test-corpus.xml`) into SaveAsXML-shaped fixtures, one test per case, asserting what is and isn't redacted. For example: `https://api.example.com/v2/ok` must survive, and `4111 1111 1111 1112` (fails Luhn) must survive.
- **Lexer unit tests**: escapes, `¶`, nested comments in strings, unterminated strings (lex as best effort, never crash).
- **Structure-preservation test** (built as a seeded generator of mixed calcs rather than a Hypothesis dependency): for any calc, the token stream after redaction equals the token stream before, ignoring `STRING` / `COMMENT` contents.
- **Idempotence**: `redact(redact(x)) == redact(x)`, with no new findings on the second run.
- **No-op on clean input**: `EverythingBagel.xml` produces byte-identical Markdown before and after this feature, except for the new report page. Any diff is a false positive to triage.
- **Guard tests**: plant a secret in a field the engine doesn't scan and assert exit 2.
- **Performance**: `NEXUS_saxml.xml` (32 MB). Redaction should add under 15% to `build` time. Compile patterns once and pre-filter strings with cheap substring checks (`"` present, `://` present, key prefixes) before tokenizing.

### 6.9 Phases

**Phase 1: foundation, on by default. Done.**
- `calc_lexer`, engine, placeholders, walker, report page, guard.
- Detectors: known keys (§2.1 + §5.7 shapes), keyword assignments (including inside commented-out code) and JSON colon forms, HTTP headers, URL secrets, connection strings, hosts / UNC / bare internal FQDNs / home dirs, base64 user:pass, PEM. PII (email, cards) at `standard`.
- Pulled forward from Phase 2/3: `diff` with a shared registry, the `strict` level (entropy plus account / modified-by names), and `--disable-scrubbing`.
- Wired into `build`, `parse`, `render`, `diff`, `inspect` and `validate`, with model metadata and `--scrub-level` / `--scrub-keyword` / `--scrub-allow`.
- Tests: the ported corpus, the lexer, structure preservation and idempotence over generated mixes, whole-model runs, and CLI end to end (including guard failure and an unscrubbed `model.json`). The three sample exports were checked by hand. EverythingBagel has nothing to redact. disRenewalUniverse and NEXUS have only real findings (author emails in custom-function headers, a home-folder username), after one false positive was fixed (a `_searchToken = "¶"` delimiter).
- Known Phase 1 gap: a plain password in a credential-*named* Set Variable (`Set Variable [$password; "hunter2"]`) is only caught when the value has a recognisable shape. The variable name sits in `<Name value=…>`, which the parser doesn't extract yet. This is the first item of Phase 2.

**Phase 2: structure-aware. Done.**
- Parser: Set Variable's name (`variable` on the raw step, `parameters.variable` on the step entity).
- Walker: every step calc carries a `StepCtx`. A step's joined `calculation` and `raw_text` preview are re-derived from the scrubbed per-parameter calcs, so a short structural password that is too risky to substitute everywhere still can't survive in the copies.
- Structural rules (verified against real exports): `Parameter type="Password"` (Re-Login 138, Reset Account Password 136, Add Account 134, …); Configure AI Account 212 / Configure RAG Account 227; Set Variable 141 into a credential-named variable (value slot only, not the repetition); Set Field 76 / Insert Calculated Result 77 into a credential-named field; Set Field By Name 147 whose target names one.
- Positional: JSONSetElement (flat and `[key; value; type]`), CryptEncrypt / CryptDecrypt (+Base64) key, CryptAuthCode key, CryptGenerateSignature key and password, MBS selectors that set a password / token / secret / licence (last argument), `MBS("Register")`, `*_Register`.
- Value handling: a literal is redacted. An expression has its literals redacted only when it is a plain concatenation. If it calls a function, the literals are arguments such as JSON key names, not the secret. A `$var` or Let local is first looked for within the calc, then traced to the nearest earlier Set Variable in the script; a `$$global` is traced to every Set Variable in the file. Unresolved variables and field references are **flagged**.
- Prose in comments and text: the value after "password is" / "API key:" is redacted when it has digits, symbols or mixed case. A long plain word is flagged with a masked preview. Ordinary wording ("password is required", "Authorization: Bearer ") is left alone.
- Name heuristics: FileMaker tags (`tokenUri_g`) are stripped before the non-secret suffix check. More non-secret suffixes were added (`scope`, `server`, `file`, …).
- Report: a "Needs review" section for flagged items. Summary line and `--fail-on-secrets`. `ENGINE_VERSION` went to 2, so models scrubbed by Phase 1 are re-scrubbed on `render`.
- Validated on the sample exports. The real hardcoded Re-Login password in disRenewalUniverse, which **Phase 1 leaked** into `entities.json`, the script page and `model.json`, is now redacted everywhere. NEXUS raises two useful flags (a private key and an RSA signing key read from fields) and no false positives. Two false-positive patterns found along the way were fixed: JSON path keys in `JSONGetElement` and `_g`-tagged names.
- Not done: Send Mail SMTP and Execute SQL ODBC credentials are covered only if FileMaker writes them as `Parameter type="Password"`. No sample export has them configured, so this is unverified. Structural Set Field rules don't apply when re-scrubbing a saved `model.json`, because step entities don't keep the target field name.

**Phase 3: extras. Done.**
- Fingerprint placeholders: `FM_SAXML_SCRUB_SALT` (at least 16 characters, read from the environment so it stays out of shell history), HMAC-SHA256, 6 hex characters, lengthened on a prefix collision. `diff` warns when saved models' placeholders aren't comparable.
- Strict PII: phone numbers (NANP and international, separators required), IBAN (mod-97), US SSN, Canadian SIN (Luhn).
- `fm-saxml:allow` in a calc *comment* (or anywhere in a text value) leaves it as written, and allows its values everywhere. Listed under "Allowed" in the report.
- `fm-saxml scrub` (§6.7).
- Fixes found while validating: an empty placeholder registry was falsy, which silently dropped the salt; card numbers no longer match digit runs inside hex; the prose rule ignores `Table::field` names; more programming words were added to the prose stop list. `ENGINE_VERSION` is now 3.
- Known gaps:
  - personal names in free text aren't detected (e.g. a first name in an Import Records folder path);
  - binary streams aren't inspected;
  - pre-existing: progress spinners crash with `UnicodeEncodeError` when stdout is redirected to `NUL` on Windows (cp1252). This affects `build`, `inspect` and `scrub` alike.

---

## 7. Open questions and risks

- **Step ids and parameter shapes in SaveAsXML.** Resolved for Re-Login, Reset Account Password and Set Variable / Set Field / Set Field By Name, from real exports (see the format note in §5.2). Still unverified: how Send Mail writes SMTP credentials, Execute SQL's ODBC password, and Configure AI / RAG Account's parameters when filled in. No sample export has them configured.
- **False positives on `key=` / `code=` query params and `[HOST]` for single-label hosts.** The original accepts over-redaction as the right failure direction. We agree for credentials. For hosts at `standard` level, check how noisy single-label matching is on real solutions.
- **Emails at `standard`.** Business emails in Send Mail steps (`support@company.com`) are often useful context. Option: redact only the local part (`[EMAIL]@company.com`) at `standard`, and the whole address at `strict`.
- **The guard only proves the absence of known values.** A secret no detector recognized is invisible to it. The docs must keep saying "review before sharing".
- **Licence.** The scrubber is CC BY 4.0. Porting its patterns and approach requires attribution: a credit in `README.md` and in the `redact/__init__.py` docstring, linking the repository and naming the author and version. This project is MIT. CC BY 4.0 is compatible as long as attribution is kept, but the ported pattern registry should carry its own attribution header, since MIT alone doesn't require downstream credit.
