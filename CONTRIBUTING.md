# Contributing

Thanks for helping improve Next Level.

## Before opening a pull request

1. Keep changes focused and avoid committing credentials or `.env` files.
2. Preserve the text-only fallback: a broken image or LLM endpoint must not block a post.
3. Add or update tests for behavior changes.
4. Run:

```bash
python -m unittest discover -s tests -v
python -m py_compile bot.py
```

For source changes, verify that the publisher exposes a stable RSS or Atom feed and allows links and short excerpts under its terms.

## Reporting a bug

Include the Python version, deployment platform, redacted configuration, relevant log lines, and a minimal reproduction. Never include bot tokens or API keys.
