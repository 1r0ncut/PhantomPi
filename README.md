<p align="center">
  <img src="docs/images/phantompi-logo.png" alt="PhantomPi Logo"/>
</p>

<h1 align="center">PhantomPi: A Covert Red Team Implant</h1>

<p align="center">
  <img src="https://img.shields.io/badge/PLATFORM-Raspberry_Pi_4-C51A4A?style=flat-square" alt="Platform"/>
  <img src="https://img.shields.io/badge/OS-Kali_Linux_ARM-557C94?style=flat-square" alt="OS"/>
  <img src="https://img.shields.io/badge/LICENSE-MIT-green?style=flat-square" alt="License"/>
  <img src="https://img.shields.io/badge/STATUS-Under_Development-orange?style=flat-square" alt="Status"/>
</p>

<p align="center">
  <sub><i>Developed during my work at <a href="https://www.inthecyber.com/">InTheCyber Group</a></i></sub>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#hardware">Hardware</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#installation">Installation</a> •
  <a href="#3d-enclosure">3D Enclosure</a> •
  <a href="#changelog">Changelog</a>
</p>

---

## Overview

**PhantomPi** is a Raspberry Pi-based network implant for red team operations requiring physical access. It positions itself inline between a corporate asset and the network switch, transparently forwarding all traffic while:

- Bypassing 802.1X/NAC by forwarding EAPOL frames
- Spoofing the inline device's identity (IP, MAC, hostname)
- Capturing network traffic and harvesting credentials in real-time
- Maintaining persistent access via 4G/LTE out-of-band channel

> [!NOTE]
> **📖 Technical Deep Dive on Medium**
> 
> [**Part 1**](https://posts.inthecyber.com/phantompi-a-covert-red-team-implant-part-1-8976a72c34d0): Hardware assembly, LTE modem configuration, WireGuard VPN, Resilience measures, Discord C2 bot
> 
> [**Part 2**](https://posts.inthecyber.com/phantompi-a-covert-red-team-implant-part-2-d74493d731ee): Bridge mode, traffic interception, 802.1X/NAC bypass, identity spoofing, 3D-printed enclosure

## Gallery

---

<div align="center">

<img src="docs/images/outside.jpg" width="100%" alt="PhantomPi"/>

<br/>

<details>
<summary><b>📸 View full gallery<b></summary>
<br/>

<table width="100%">
  <tr>
    <td width="50%" align="center">
      <img src="docs/images/components.jpg" width="100%"/>
    </td>
    <td width="50%" align="center">
      <img src="docs/images/inside.jpg" width="100%" alt="Assembled"/>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="docs/images/assembled.jpg" width="100%" alt="Back"/>
    </td>
    <td width="50%" align="center">
      <img src="docs/images/front.jpg" width="100%" alt="Outside"/>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="docs/images/upside.jpg" width="100%" alt="Back"/>
    </td>
    <td width="50%" align="center">
      <img src="docs/images/back.jpg" width="100%" alt="Outside"/>
    </td>
  </tr>
</table>

</details>

</div>

## Features

| Capability | Description |
|------------|-------------|
| **Transparent Bridging** | Layer 2 bridge with `group_fwd_mask=8` for 802.1X EAPOL passthrough |
| **Identity Spoofing** | Auto-detection of target IP/MAC via ARP, hostname via LLDP, gateway and DNS |
| **Out-of-Band Control** | 4G/LTE modem (RNDIS) + WireGuard VPN + Discord bot management |
| **Traffic Interception** | Continuous packet capture with rolling PCAP storage + credential extraction with Discord alerts |
| **Resilience** | Hardware watchdog, WireGuard auto-reconnect, hidden WiFi AP fallback |

## Hardware

### Bill of Materials

#### Core Modules
| Component | Link |
|-----------|------|
| Raspberry Pi 4 – Model B | [Amazon](https://amzn.eu/d/08y3z1Lm) |
| Waveshare 4G HAT (SIM7600G-H) | [Amazon](https://www.amazon.it/dp/B0824P4B7M) |
| PoE HAT Module | [Amazon](https://www.amazon.it/dp/B0928ZD7QQ) |
| Witty Pi 4 (RTC & Power Management) | [UUGear](https://www.uugear.com/product/witty-pi-4/) |

#### Networking & Wireless
| Component | Link |
|-----------|------|
| USB-Ethernet Adapter | [Amazon](https://www.amazon.it/dp/B09FDRMZ73) |
| 4G Antenna SMA 6 dBi Omnidirectional | [Amazon](https://www.amazon.it/dp/B0CQYD3SXS) |
| RP-SMA to U.FL Low-Loss Coaxial Cable | [Amazon](https://www.amazon.it/dp/B0C89RPVYQ) |
| EIOTCLUB SIM Card | [Amazon](https://www.amazon.it/dp/B0D7ZKPVH9) |

#### Connectors & Cables
| Component | Link |
|-----------|------|
| Right-Angle Micro USB Connector | [Amazon](https://www.amazon.it/dp/B0C36JV6ST) |
| Ribbon USB Cable – 20 cm | [Amazon](https://www.amazon.it/dp/B0C36K629Z) |
| USB-A Connector | [Amazon](https://www.amazon.it/dp/B0C36JJC33) |
| Right-Angle USB-C to USB-C Cable – 30 cm | [Amazon](https://www.amazon.it/dp/B0DKHGM7FR) |
| Passthrough USB-C Adapter | [Amazon](https://www.amazon.it/dp/B09XDWFYRP) |
| Passthrough Ethernet Adapter | [Amazon](https://www.amazon.it/dp/B0CYGSF5WR) |
| Flexible Ethernet Cables – 25 cm | [Amazon](https://www.amazon.it/dp/B0DBQPZS4R) |

#### Mounting & Build Materials
| Component | Link |
|-----------|------|
| Raspberry Pi Spacer Kit | [Amazon](https://www.amazon.it/dp/B07MN2GY6Y) |
| Brass Hex Spacer M2.5 × 15+6 mm (Male-Female) | [Amazon](https://www.amazon.it/dp/B0BTYP6MCQ) |
| Brass Hex Spacer M2.5 × 16+6 mm (Male-Female) | [Amazon](https://www.amazon.it/dp/B0BTYQF6H8) |
| Self-Tapping Screws – M2 / M2.3 / M2.6 / M3 | [Amazon](https://www.amazon.it/dp/B09NDPGJG1) |
| PLA Filament – 1 Kg | [Amazon](https://amzn.eu/d/0MXtUJm) |
| Portable Case | [Amazon](https://www.amazon.it/dp/B09PRBBH6P) |

### Assembly Instructions

The implant is built by stacking the boards and modules using M2.5 spacers of specific lengths:

| Layer | Spacer Type | Spacer Length |
|-------|-------------|---------------|
| Bottom → Pi 4 | M2.5 Male-Female | 5 mm + 5 mm |
| Pi 4 → PoE HAT | M2.5 Male-Female | 16 mm + 6 mm |
| PoE HAT → 4G HAT | M2.5 Male-Female | 16 mm + 6 mm |
| 4G HAT → Witty Pi 4 | M2.5 Male-Female | 11 mm + 6 mm |
| Witty Pi → Printed Top HAT | M2.5 Female-Female | 11 mm |
| Top Screws on Printed HAT | M2.5 Screws | — |
| Case Cover Screws | M2.6 Screws | — |

> ⚠️ **USB Port Assignment**: The LTE module and USB-to-Ethernet adapter must be connected to specific USB ports to ensure consistent interface naming (`eth1`, `eth2`). See [USB port mapping](https://medium.com/inthecyber-posts/phantompi-a-covert-red-team-implant-part-2-d74493d731ee#0db1) in the Part 2 article.

### Interface Mapping

| Interface | Role |
|-----------|------|
| `eth0` | Corporate network (PoE powered) |
| `eth1` | LTE modem (RNDIS mode) |
| `eth2` | Inline device connection |

## Architecture

```mermaid
flowchart TB
    WG["WireGuard Server (Operator VPS)"]
    
    subgraph PhantomPi
        eth0[eth0]
        br0[br0]
        eth1["eth1 (LTE)"]
        wg0["wg0 (WireGuard VPN)"]
        eth2[eth2]
        
        eth0 --- br0
        br0 --- eth2
        eth1 --- wg0
    end
    
    SW["Corporate Switch"] --- eth0
    eth2 --- DEV["Inline Device (e.g. Workstation)"]
    wg0 ---|4G/LTE| WG
```

## Installation

> [!IMPORTANT]
> These scripts have been tested only on the exact hardware and software configuration detailed in this repository and in the Medium articles. Other setups may require adjustments.

### Implant (Raspberry Pi)

1. Flash **Kali Linux ARM** onto the Raspberry Pi 4 SD card
2. Clone this repository and fill in the configuration:
   ```bash
   git clone https://github.com/1r0ncut/PhantomPi.git
   cd PhantomPi/implant
   nano setup/init.json          # fill WireGuard, LTE, hotspot, Discord values
   ```
3. Run the setup script:
   ```bash
   sudo bash setup.sh
   ```
4. Reboot the implant:
   ```bash
   sudo reboot
   ```

> Use `sudo bash setup.sh --debug` for verbose output.
>
> To undo everything and re-run from scratch:
> ```bash
> sudo bash setup/reset.sh          # quick reset (keeps WG keys)
> sudo bash setup/reset.sh --full   # full reset (removes everything)
> ```

#### Resulting Filesystem Layout

```
/opt/implant/
├── config.env              # Central configuration
├── api/                    # Flask/Gunicorn HTTPS API (port 8443)
│   ├── routes/             # Standalone route modules
│   ├── certs/              # Self-signed TLS certificate
│   └── venv/               # Python virtual environment
├── scripts/
│   ├── bridge-sync.sh      # Bridge lifecycle (auto create/teardown)
│   ├── cred-analyzer.py    # Scapy-based PCAP credential extractor
│   ├── spoof-target.sh     # Identity detection & spoofing
│   ├── wg-keepalive.sh     # VPN auto-reconnect
│   ├── hidden-hotspot.sh   # Emergency WiFi AP
│   ├── modem-config.sh     # LTE modem AT commands
│   └── trigger-lldp.py     # LLDP hostname extraction
├── logs/
│   ├── packet-sniffer/     # Rolling PCAP captures
│   └── cred-analyzer/      # findings.json + state.json
├── services/               # systemd service units
├── timers/                 # systemd timer units
└── wittypi/                # Witty Pi 4 power management + UWI
```

### VPS (Operator Server)

1. Clone this repository on your VPS and fill in the configuration:
   ```bash
   git clone https://github.com/1r0ncut/PhantomPi.git
   cd PhantomPi/vps
   nano setup/init.json          # fill Discord token, guild ID, WireGuard peers
   ```
2. Run the setup script:
   ```bash
   sudo bash setup.sh
   ```
3. Verify:
   ```bash
   wg show
   systemctl status openclaw
   ```

> To undo everything and re-run from scratch:
> ```bash
> sudo bash setup/reset.sh          # quick reset (keeps WG keys)
> sudo bash setup/reset.sh --full   # full reset (removes everything)
> ```

#### Resulting Filesystem Layout

```
/opt/implant/openclaw/
├── openclaw.json           # OpenClaw configuration
├── skills/
│   ├── implant-status/     # Natural-language status queries
│   ├── cred-sniffer/       # Credential analysis & reporting
│   └── bridge-sync/        # Bridge event notifications
└── logs/                   # OpenClaw runtime logs
```

## 3D Enclosure

STL files for the custom 3D-printed case:

| File | Description |
|------|-------------|
| [`phantompi-implant-case.stl`](docs/3d-models/phantompi-implant-case.stl) | Main enclosure (body + cover) |
| [`usb-to-eth-adapter-hat.stl`](docs/3d-models/usb-to-eth-adapter-hat.stl) | USB-to-Ethernet adapter mount |

## Changelog

- **[v1.1](https://github.com/1r0ncut/PhantomPi/releases/tag/v1.1)**: Replaced Discord bot with OpenClaw AI assistant; real-time credential push via webhook, natural-language C2, modular skill system ([Implant API and OpenClaw Skills](docs/skills-and-api.md))
- **[v1.0](https://github.com/1r0ncut/PhantomPi/releases/tag/v1.0)**: Initial release, transparent bridge, 802.1X bypass, identity spoofing, LTE out-of-band C2, Discord bot

