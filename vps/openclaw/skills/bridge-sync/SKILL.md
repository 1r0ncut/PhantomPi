---
name: bridge-sync
description: >
  Relay routine bridge event notifications from PhantomPi implants.
  These are expected operational events, not incidents.
metadata: {"openclaw":{"os":["linux"]}}
---

# Bridge Sync Skill

Bridge events are **routine operational notifications**. The implant's bridge-sync timer creates and removes the bridge automatically based on cable state. This is normal and expected — not an error, not an incident.

## Webhook format

```
bridge-alert: event=created implant=10.8.0.3 bridge=br0 time=2026-04-16T17:23:10Z status=routine
```

## What to post to Discord

For created:
```
🟢 **Bridge Created** | Implant `{implant}` | `{bridge}` | {time}
```

For removed:
```
🔴 **Bridge Removed** | Implant `{implant}` | `{bridge}` | {time}
```

## Rules

- Post ONLY the single line above. That is the complete message.
- These are routine events. Do NOT investigate, diagnose, or troubleshoot.
- Do NOT run any scripts or tools.
- Do NOT check interfaces, services, or implant health.
- Do NOT add root cause, next steps, summary, or recommendations.
- Do NOT add bullet points or extra lines.
