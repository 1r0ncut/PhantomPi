"""
PhantomPi Setup — Configuration Loader & Validator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Loads ``init.json``, provides safe nested access, and validates that
every field required for a functional implant is present.
"""

from __future__ import annotations

import json
import os


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    """Read and parse the JSON configuration file."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with open(path, "r") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Safe nested access
# ---------------------------------------------------------------------------

def get(config: dict, *keys, default=None):
    """
    Walk *keys* into a nested dict, returning *default* when any key is
    missing.

    >>> get(cfg, "wireguard", "server_public_key", default="")
    """
    current = config
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def get_implant_ip(config: dict) -> str:
    """
    Return the bare IPv4 address from ``wireguard.implant_address``
    (strips the CIDR suffix, e.g. ``10.8.0.3/24`` -> ``10.8.0.3``).
    """
    addr = get(config, "wireguard", "implant_address", default="10.8.0.3/24")
    return addr.split("/")[0]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_config(config: dict) -> list[str]:
    """
    Check the configuration and return a list of human-readable warnings
    for values that are empty or invalid.  Each warning describes what
    will be *skipped* during setup because of the missing value.
    """
    warnings: list[str] = []

    # -- WireGuard (critical for remote access) ----------------------------
    wg = config.get("wireguard", {})
    if not wg.get("server_public_key"):
        warnings.append(
            "wireguard.server_public_key is empty "
            "— WireGuard tunnel config will NOT be generated"
        )
    if not wg.get("server_public_ip"):
        warnings.append(
            "wireguard.server_public_ip is empty "
            "— WireGuard tunnel config will NOT be generated"
        )
    if not wg.get("server_port"):
        warnings.append(
            "wireguard.server_port is empty "
            "— WireGuard tunnel config will NOT be generated"
        )
    if not wg.get("implant_private_key"):
        warnings.append(
            "wireguard.implant_private_key is empty "
            "— a new key pair will be generated automatically"
        )

    # -- LTE modem ---------------------------------------------------------
    lte = config.get("lte", {})
    if not lte.get("apn"):
        warnings.append(
            "lte.apn is empty "
            "— modem APN will NOT be set automatically"
        )

    # -- Hotspot -----------------------------------------------------------
    hs = config.get("hotspot", {})
    psk = hs.get("psk", "")
    if not psk or len(psk) < 8:
        warnings.append(
            "hotspot.psk is empty or shorter than 8 characters "
            "— hotspot profile will NOT be created"
        )

    # -- Discord notifications (nice-to-have) ------------------------------
    dc = config.get("discord", {})
    if not dc.get("bridge_sync_webhook_url"):
        warnings.append(
            "discord.bridge_sync_webhook_url is empty "
            "— bridge up/down notifications disabled"
        )
    if not dc.get("bruteshark_webhook_url"):
        warnings.append(
            "discord.bruteshark_webhook_url is empty "
            "— credential-extraction notifications disabled"
        )

    return warnings
