import random
import time
from scapy.all import Ether, Raw, sendp

# The interface connected to the target device
IFACE = "eth2"

# 1. Create a single, random identity for this entire transaction.
chassis_mac_bytes = bytes([0x02] + [random.randint(0x00, 0xFF) for _ in range(5)])
chassis_mac_str = chassis_mac_bytes.hex(':')

# 2. Construct LLDP TLVs

# --- Chassis ID TLV (Type 1) ---
# Type: 1, Length: 7, Subtype: 4 (MAC address)
chassis_id_tlv = b'\x02\x07\x04' + chassis_mac_bytes

# --- Port ID TLV (Type 2) ---
# Type: 2, Length: 5, Subtype: 7 (Locally assigned), Value: "eth0"
port_id_tlv = b'\x04\x05\x07' + b'eth0'

# --- Time To Live TLV (Type 3) ---
# TTL: 120 seconds
ttl_advertise_tlv = b'\x06\x02\x00\x78'

# --- End of LLDPDU TLV (Type 0) ---
end_tlv = b'\x00\x00'

# --- Compose and send advertisement packet ---
lldp_payload_advertise = chassis_id_tlv + port_id_tlv + ttl_advertise_tlv + end_tlv
pkt_advertise = Ether(dst="01:80:c2:00:00:0e", src=chassis_mac_str, type=0x88cc) / Raw(load=lldp_payload_advertise)
sendp(pkt_advertise, iface=IFACE, count=1, verbose=False)

# --- Wait and send shutdown packet ---
time.sleep(1)
ttl_shutdown_tlv = b'\x06\x02\x00\x00'
lldp_payload_shutdown = chassis_id_tlv + port_id_tlv + ttl_shutdown_tlv + end_tlv
pkt_shutdown = Ether(dst="01:80:c2:00:00:0e", src=chassis_mac_str, type=0x88cc) / Raw(load=lldp_payload_shutdown)
sendp(pkt_shutdown, iface=IFACE, count=1, verbose=False)
