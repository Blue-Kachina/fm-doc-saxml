"""Fake credentials for the scrubbing tests, assembled at runtime.

Secret scanners (GitHub push protection, gitleaks, …) match key *shapes* in source
text and can't tell a test fixture from a leak. Each value here is split at its
provider prefix, so no complete key ever appears as one literal in the repo, while
the tests still see exactly the strings they check. ``test_no_key_shaped_literals``
in ``test_scrub_detectors.py`` keeps it that way. None of these are real.
"""

OPENAI = "sk-" + "proj-abcdef1234567890"
OPENAI_LONG = OPENAI + "XYZ"
OPENAI_OTHER = "sk-" + "proj-ZZZZZZZZZZZZZZZZZZZZ"
OPENAI_PUBLIC = "sk-" + "proj-PUBLICTESTKEY0001"
OPENAI_REAL = "sk-" + "proj-REALSECRETKEY0002"
OTTO_DATA = "dk" + "_9f8e7d6c5b4a"
OTTO_ADMIN = "ak" + "_KFji7VzNDO123"
AWS_KEY_ID = "AKIA" + "IOSFODNN7EXAMPLE"  # AWS's own documentation example
GITHUB = "ghp" + "_" + "a" * 36
JWT_HEADER = "eyJhbGciOiJIUzI1NiJ9"
JWT = ".".join([JWT_HEADER, "eyJzdWIiOiIxMjM0NTY3ODkwIn0", "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"])
SLACK_WEBHOOK_PATH = "T000/B000/XXXXXXXX"
SLACK_WEBHOOK = "https://hooks.slack" + ".com/services/" + SLACK_WEBHOOK_PATH
# Shaped like a Stripe live secret key, used as a *field name* the scrubber must leave alone.
STRIPE_SHAPED_NAME = "sk" + "_live_FieldNameThatLooksLikeAKey1234"
