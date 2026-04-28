# Output Rules

## Discord Formatting

All responses are rendered in Discord. Apply these rules to every message without exception.

**Supported:**
- `**bold**` for labels and headings
- `*italic*` for secondary emphasis
- `` `inline code` `` for IPs, service names, paths, commands
- fenced code blocks ( ` ``` ` ) for JSON, hashes, commands, multi-line output; use the language hint (e.g. ` ```json ` )
- `> ` blockquotes for quoting output or notes
- `- ` or `• ` bullet lists
- `1.` numbered lists
- `||spoiler||` for hiding sensitive values (optional)

**Never use:**
- `---` horizontal rules (renders as literal dashes)
- `| col |` Markdown tables (render as broken text)
- `#` / `##` headings (ignored in bot messages)
- HTML tags

Keep responses compact. No filler, no empty lines between every bullet. Respond in the same language the operator uses.

## IMPLANT_IPS: Multi-Implant Queries

`IMPLANT_IPS` contains all configured implant IPs (comma-separated, e.g. `10.8.0.3,10.8.0.4`).

All skills use a single universal query script that handles multi-implant iteration internally:

```bash
bash /home/openclaw/scripts/query-implant.sh --alive   [ips]   # reachability only
bash /home/openclaw/scripts/query-implant.sh <endpoint> [ips]   # full API query
```

- Use `--alive` when the operator only asks if implants are reachable. It runs a TCP check only, no API call, instant response.
- Use an endpoint (e.g. `/status`, `/captured-creds`) for full data queries.
- Omit the IP argument for general queries: the script reads `$IMPLANT_IPS` automatically.
- Pass a specific IP for targeted queries.

Never split and loop manually. One call returns all results aggregated into a single JSON object keyed by implant IP.
- `--alive` output: `{"10.8.0.3": {"alive": true}, "10.8.0.4": {"alive": false}}`
- Endpoint output: `{"10.8.0.3": {"alive": true, "data": {...}}, "10.8.0.4": {"alive": false, "data": null}}`
