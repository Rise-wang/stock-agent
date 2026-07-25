# Security Policy

## Supported Versions

Only the current `main` branch is supported.

## Reporting a Vulnerability

Open a private security advisory on GitHub if available, or contact the repository owner directly.

Do not include private credentials, brokerage account data, API tokens, SSH keys, cookies, or other secrets in public issues.

## Sensitive Data

This project is designed for public market data workflows. It should not require:

- Brokerage credentials
- Trading permissions
- Private account holdings
- API secrets
- SSH private keys

If a future integration needs credentials, it must use environment variables or a local ignored config file, and documentation must clearly mark those values as secrets.
