# Security

Please report a vulnerability privately through GitHub's "Report a vulnerability" button on this repository's Security tab
(or open a private advisory). Do not open a public issue for a security problem. We aim to answer within 7 days.

What matters most here: passwords and device tokens, the public address (Tailscale Funnel), server-to-server requests between Encore
servers, and anything that could let one person see another person's library or listening. The threat model is in
[docs/21-security-privacy-and-roles.md](docs/21-security-privacy-and-roles.md).
