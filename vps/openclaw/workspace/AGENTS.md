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
bash /home/openclaw/scripts/query-implant.sh <endpoint> [ips]
```

- For general queries (all implants): omit the IP argument. The script reads `$IMPLANT_IPS` automatically.
- For targeted queries (specific IP or implant number): pass only that IP as the second argument.

Never split and loop manually. One call returns all results aggregated into a single JSON object keyed by implant IP. Unreachable implants appear as `{"alive": false, "data": null}`.
