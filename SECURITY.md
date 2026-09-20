# Security Policy

## Reporting a vulnerability

Please report security issues privately to the repository owner through the contact method on the GitHub profile. Do not open a public issue containing credentials, private channel identifiers, or an unpatched exploit.

## Secrets

- Keep Telegram and LLM credentials in environment variables or a platform secret store.
- Never commit `.env`, exported logs containing authorization headers, or a populated `posted.json` from a private deployment.
- Rotate a credential immediately if it appears in Git history, build logs, screenshots, or an issue.

The example environment file contains placeholders only.
