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

## Checking for new findings

Run the check script with the target implant IP:

```bash
bash {baseDir}/scripts/check-findings.sh ${IMPLANT_IP:-10.8.0.3}
```

The script returns JSON.  If `status` is `"inactive"` the packet-sniffer
service is not running — tell the operator.

## Finding types

| type | protocol examples | significance | action |
|------|-------------------|-------------|--------|
| `cleartext` | HTTP Basic, FTP, SMTP, POP3, IMAP, Telnet, LDAP, SNMP, Redis, MySQL, PostgreSQL | Plaintext credentials — immediately usable | Try against other services, check for reuse |
| `ntlm_hash` | NetNTLMv1/v2 (SMB, HTTP NTLMSSP) | Challenge-response hashes | Crack: `hashcat -m 5500` (v1) / `-m 5600` (v2). Or relay with `ntlmrelayx` |
| `kerberos` | AS-REP, TGS-REP | Kerberos ticket hashes | Crack: `hashcat -m 18200` (AS-REP roast) / `-m 13100` (Kerberoast) |
| `token` | Bearer, JWT, session cookies | Auth tokens | Replay for session hijacking; decode JWTs to find scope/roles |

## Reporting guidelines

1. Group by finding type, then protocol.
2. For hashes, always include the hashcat mode and a one-liner command.
3. For cleartext creds, highlight the target host and service.
4. Flag high-value accounts: Domain Admin, service accounts, `admin`, `root`.
5. When summarising, count findings per type and call out the most critical.
6. Never truncate the `secret` field — operators need the full value.
