<p align="center">
  <img src="docs/images/phantompi-logo.png" alt="PhantomPi Logo" width="400"/>
</p>

<h1 align="center">PhantomPi</h1>

<p align="center">
  <img src="https://img.shields.io/badge/PLATFORM-Raspberry_Pi_4-C51A4A?style=flat-square" alt="Platform"/>
  <img src="https://img.shields.io/badge/OS-Kali_Linux_ARM-557C94?style=flat-square" alt="OS"/>
  <img src="https://img.shields.io/badge/LICENSE-MIT-green?style=flat-square" alt="License"/>
  <img src="https://img.shields.io/badge/STATUS-Under_Development-orange?style=flat-square" alt="Status"/>
</p>

<p align="center">
  <strong>Covert network implant for physical red team engagements.</strong><br>
  Transparent Layer 2 bridging with 802.1X bypass, identity spoofing, and out-of-band LTE control.
</p>

<p align="center">
  Built by <a href="https://1r0ncut.github.io/"><strong>Alessandro Tagliafierro</strong></a> at <a href="https://www.inthecyber.com/"><strong>InTheCyber Group</strong></a>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#hardware">Hardware</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#installation">Installation</a> •
  <a href="#usage">Usage</a>
</p>

---

## Overview

**PhantomPi** is a Raspberry Pi-based network implant for red team operations requiring physical access. It positions itself inline between a corporate asset and the network switch, transparently forwarding all traffic while:

- Bypassing 802.1X/NAC by forwarding EAPOL frames
- Spoofing the inline device's identity (IP, MAC, hostname)
- Capturing network traffic and harvesting credentials in real-time
- Maintaining persistent access via 4G/LTE out-of-band channel

> 📖 **Technical Deep Dive**: [Part 1](https://posts.inthecyber.com/phantompi-a-covert-red-team-implant-part-1-8976a72c34d0) — Hardware, WireGuard, Discord bot | [Part 2](https://posts.inthecyber.com/phantompi-a-covert-red-team-implant-part-2-d74493d731ee) — Bridge mode, 802.1X bypass, spoofing


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
| Raspberry Pi 4 – Model B | [Amazon](https://www.amazon.it/Raspberry-Pi-4595-Modello-B) |
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

> ⚠️ **USB Port Assignment**: The LTE module and USB-to-Ethernet adapter must be connected to specific USB ports to ensure consistent interface naming (`eth1`, `eth2`). See documentation for port mapping.

### Interface Mapping

| Interface | Role |
|-----------|------|
| `eth0` | Corporate network (PoE powered) |
| `eth1` | LTE modem (RNDIS mode) |
| `eth2` | Inline device connection |

## Architecture

```
                              ┌──────────────────────┐
                              │   WireGuard Server   │
                              │   (Operator VPS)     │
                              └──────────┬───────────┘
                                         │ 4G/LTE
                                         │
┌────────────┐    ┌──────────────────────┼──────────────────────┐
│  Corporate │    │              PhantomPi                      │
│   Switch   │    │  ┌─────┐    ┌─────┐ │ ┌─────┐    ┌─────┐   │
│            │    │  │eth0 │────│ br0 │   │eth1 │────│ wg0 │   │
│    [G1]────┼────┼──┤     │    │     │ │ │(LTE)│    │(VPN)│   │
│            │    │  └─────┘    └──┬──┘ │ └─────┘    └─────┘   │
│            │    │               │     │                       │
│            │    │            ┌──┴──┐  │                       │
│            │    │            │eth2 │  │                       │
└────────────┘    └────────────┼─────┼──┴───────────────────────┘
                               │     │
                          ┌────┴─────┴────┐
                          │ Inline Device │
                          │ (Workstation) │
                          └───────────────┘
```

### Software Components

```
/opt/implant/
├── config.env              # Central configuration
├── scripts/
│   ├── bridge-sync.sh      # Bridge lifecycle (auto create/teardown)
│   ├── spoof-target.sh     # Identity detection & spoofing
│   ├── wg-keepalive.sh     # VPN auto-reconnect
│   ├── hidden-hotspot.sh   # Emergency WiFi AP
│   ├── modem-config.sh     # LTE modem AT commands
│   ├── trigger-lldp.py     # LLDP hostname extraction
│   └── BruteShark/         # Credential extraction
├── services/               # systemd units
├── timers/                 # systemd timers
└── discord/                # Implant-side API (Flask/Gunicorn)
```

## Installation

> 🚧 **Under Construction**
> 
> Automated installation scripts and detailed setup guides are being developed.
> Check the Medium articles for manual configuration steps.

## Usage

> 🚧 **Under Construction**
> 
> Detailed usage documentation is being developed.
> Check the Medium articles for operational guidance.

## 3D Enclosure

> 🚧 **Under Construction**
> 
> STL files coming soon. Dimensions: 140×100×100 mm with RJ45, USB-C, and SMA pass-throughs.

