# Security Policy

## Supported Versions

Emboss follows [Semantic Versioning](https://semver.org/). Security fixes are
released against the latest 1.x minor version on PyPI. Older major versions
are not maintained.

| Version | Supported |
| ------- | --------- |
| 1.x     | Yes       |
| < 1.0   | No        |

## Reporting a Vulnerability

Please **do not open a public GitHub issue** for a suspected security
vulnerability.

Report it privately via
[GitHub Security Advisories](https://github.com/GGChamp85/Emboss/security/advisories/new)
for this repository. Include:

- A description of the vulnerability and its potential impact.
- Steps to reproduce (a minimal `Document`/spec that triggers it).
- The Emboss version and Python version.

You should expect an initial response within 5 business days. If the report
is confirmed, a fix will be prepared and a new version released before
public disclosure; you will be credited in the release notes unless you
prefer otherwise.

## Scope

In scope: the `emboss` Python package itself (rendering, parsing, PDF
assembly, the MCP server, and the CLI). A dependency's own vulnerability
should generally be reported to that project directly; if it materially
affects Emboss users (e.g. a transitive dependency with no fixed floor),
please still report it here so the constraint can be tightened.

## Dependency Security

The only hard runtime dependency is `fonttools`. `pydantic`, `pikepdf`,
`cryptography`, and `mcp` are optional extras. Dependency vulnerabilities
are monitored via Dependabot alerts and periodically audited with
`pip-audit` against the full dependency set (base plus every extra); known
floors are pinned in `pyproject.toml` when a transitive dependency sets none
of its own.
