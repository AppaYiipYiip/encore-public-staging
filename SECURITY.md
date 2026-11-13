# Security

Please report a vulnerability privately through GitHub's "Report a vulnerability" button on this repository's Security tab
(or open a private advisory). If that button is not there yet, open an issue titled "security contact" with **no technical details**, and we
will reply with a private way to send them. Never put the details of a security problem in a public issue. We aim to answer within 7 days.

What matters most here: passwords and device tokens, the public address (Tailscale Funnel), server-to-server requests between Encore
servers, and anything that could let one person see another person's library or listening. The threat model is in
[docs/21-security-privacy-and-roles.md](docs/21-security-privacy-and-roles.md).
