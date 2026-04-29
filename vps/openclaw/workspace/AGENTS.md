# Output Rules

## Discord Formatting

All responses are rendered in Discord. Use standard Discord markdown: bold, italic, inline code, fenced code blocks (with language hint), blockquotes, bullet and numbered lists.

**Never use:**
- `---` horizontal rules (renders as literal dashes)
- `| col |` Markdown tables (render as broken text)
- `#` / `##` headings (ignored in bot messages)
- HTML tags

Keep responses compact. No filler, no empty lines between every bullet. Respond in the same language the operator uses.

## IMPLANT_IPS: Multi-Implant Queries

`IMPLANT_IPS` contains all configured implant IPs (comma-separated). Always use the universal query script — never loop manually:

```bash
bash /home/openclaw/scripts/query-implant.sh --alive [ips]      # TCP check only
bash /home/openclaw/scripts/query-implant.sh <endpoint> [ips]   # GET, all implants
bash /home/openclaw/scripts/query-implant.sh --post <endpoint> <json> [ip]  # POST, single implant
```

Omit IP to use `$IMPLANT_IPS` automatically. Output is keyed by implant IP: `{"10.8.0.3": {"alive": true, "data": {...}}, ...}`

**Never invent or guess API endpoint names.** Only use endpoints explicitly listed in the active skill. If unsure, re-read the skill before acting.
