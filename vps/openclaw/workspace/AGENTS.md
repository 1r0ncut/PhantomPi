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

`IMPLANT_IPS` is a comma-separated environment variable listing all configured implant IPs (e.g. `10.8.0.3,10.8.0.4`).

Rules for any skill that queries implants:
- Always split on commas. Never pass the full string as a single IP argument to a script.
- For general queries (operator asks about all implants): iterate over each IP, run the script once per IP, aggregate results.
- For targeted queries (operator names a specific IP or implant number): query only that one.
