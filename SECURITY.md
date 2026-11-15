# Security and data safety

Atlas runs a loopback-only local server. File-changing requests use a session token,
validate the plan, check file contents and refuse overwrites. These are safeguards,
not a guarantee against every failure. Keep backups of irreplaceable work.

The scan is read-only. Project analysis does not run scanned code or package scripts.
Exported plans and AI context can contain private filenames and paths. The repo's agent
instructions are guidance for an external agent, not an operating-system access boundary.

## Reporting a vulnerability

Use the repository's **Security → Report a vulnerability** private channel when available.
If private reporting has not been enabled, open a minimal issue requesting a private
contact; do not include exploit instructions, credentials, personal paths or private files.

For ordinary bugs, use a small synthetic reproduction. Remove tokens and private paths
from logs and screenshots. There is no promised response time or long-term support policy yet.
