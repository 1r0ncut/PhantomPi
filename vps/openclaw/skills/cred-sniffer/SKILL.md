---
name: cred-sniffer
description: >
  Monitor PhantomPi implant packet captures for cleartext credentials,
  NTLM hashes, Kerberos tickets, and authentication tokens found during
  red-team engagements. Triggers on: credentials, hashes, creds, sniffer,
  captures, pcap, kerberos, ntlm, tokens, passwords.
metadata: {"openclaw":{"requires":{"bins":["curl"]},"os":["linux"]}}
---

# Credential Sniffer

You analyse network traffic captures from PhantomPi implants for
security-relevant credentials during **authorised** red-team engagements.

## Checking for captured credentials

```bash
bash /home/openclaw/scripts/query-implant.sh /captured-creds [IMPLANT_IPS]
```

Omit the IP argument for general queries; the script reads `$IMPLANT_IPS` and checks all implants automatically.
Pass a specific IP for targeted queries. The script returns a JSON object keyed by implant IP, with `alive` and `data` fields per implant.

Returns JSON with fields:
- `implant`: the queried IP
- `sniffer` / `analyzer`: service status (`active` or `inactive`)
- `count`: total credential findings
- `types`: breakdown by type
- `findings`: full credential list

If `sniffer` is `"inactive"` the packet-sniffer is not running. Tell the operator.

## Finding types

- **cleartext** (HTTP Basic, FTP, SMTP, POP3, IMAP, Telnet, LDAP, SNMP, Redis, MySQL, PostgreSQL): plaintext credentials, immediately usable. Try against other services, check for reuse.
- **ntlm_hash** (NetNTLMv1/v2 via SMB, HTTP NTLMSSP): challenge-response hashes. Crack: `hashcat -m 5500` (v1) / `-m 5600` (v2). Or relay with `ntlmrelayx`.
- **kerberos** (AS-REP, TGS-REP): Kerberos ticket hashes. Crack: `hashcat -m 18200` (AS-REP roast) / `-m 13100` (Kerberoast).
- **token** (Bearer, JWT, session cookies): auth tokens. Replay for session hijacking; decode JWTs to find scope/roles.

## Reporting guidelines

1. Group by implant (when multiple), then by finding type, then protocol.
2. For hashes, always include the hashcat mode and a one-liner command.
3. For cleartext creds, highlight the target host and service.
4. Flag high-value accounts: Domain Admin, service accounts, `admin`, `root`.
5. When summarising, count findings per type and call out the most critical.
6. Never truncate the `secret` field. Operators need the full value.

## Webhook alerts (cred-alert)

Messages starting with `cred-alert:` are routine automated notifications from
the implant's credential analyzer. They are NOT incidents, just new findings.

Webhook format:
```
cred-alert: implant=10.8.0.3 count=2
protocol=HTTP Basic Auth | type=cleartext | user=admin | secret=P@ssw0rd | src=192.168.1.50:49312 | dst=192.168.1.10:80
protocol=SMB/NTLMSSP | type=ntlm_hash | user=jdoe | secret=jdoe::CORP:1122... | src=192.168.1.50:49320 | dst=192.168.1.5:445
```

When delivering a cred-alert to Discord, use this template:

```
🔑 **Credentials Found** | Implant `{implant}` | {count} new

{for each finding:}
`{protocol}` {user} → `{dst}`
`{secret}`
```

Per-type additions:
- **cleartext**: append ⚠️ before the protocol
- **ntlm_hash**: append `hashcat -m 5600` (NTLMv2) or `-m 5500` (NTLMv1) after the secret
- **kerberos**: append `hashcat -m 18200` (AS-REP) or `-m 13100` (Kerberoast) after the secret
- **token**: append 🪪 before the protocol

Do not run scripts, check status, or add extra commentary beyond the template.
Never truncate the secret field.
