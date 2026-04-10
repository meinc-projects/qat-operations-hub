# Cloudflare Tunnel — VPS Setup Guide

## Overview

A single Cloudflare Tunnel runs on the DatabaseMart VPS (38.247.188.233) and exposes local apps to the internet via `quickautotags.com` subdomains. No inbound ports need to be opened — the tunnel creates an outbound connection to Cloudflare, which handles HTTPS/SSL automatically.

**Tunnel name:** `qat-hub`
**Tunnel ID:** `07be7746-7121-44fe-86db-3d9347a72c03`
**Domain:** `quickautotags.com` (managed in Cloudflare)
**Runs as:** Windows Service (`Cloudflared`) — survives reboots

---

## Key Files

| File | Purpose |
|------|---------|
| `C:\Users\Administrator\.cloudflared\config.yml` | Tunnel routing config |
| `C:\Users\Administrator\.cloudflared\07be7746-7121-44fe-86db-3d9347a72c03.json` | Tunnel credentials (keep secret) |
| `C:\Users\Administrator\.cloudflared\cert.pem` | Cloudflare origin certificate |

---

## Current Routing

| Subdomain | Local Service | App |
|-----------|--------------|-----|
| `hub.quickautotags.com` | `http://localhost:8100` | QAT Operations Hub |

---

## Adding a New App

### Step 1: Edit the tunnel config

Open `C:\Users\Administrator\.cloudflared\config.yml` and add a new ingress rule **before** the catch-all line:

```yaml
tunnel: 07be7746-7121-44fe-86db-3d9347a72c03
credentials-file: C:\Users\Administrator\.cloudflared\07be7746-7121-44fe-86db-3d9347a72c03.json

ingress:
  - hostname: hub.quickautotags.com
    service: http://localhost:8100
  - hostname: newapp.quickautotags.com       # <-- add new app here
    service: http://localhost:XXXX            # <-- local port of the new app
  - service: http_status:404                 # <-- catch-all MUST stay last
```

### Step 2: Add DNS route

```powershell
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel route dns qat-hub newapp.quickautotags.com
```

This creates a CNAME record in Cloudflare DNS automatically.

### Step 3: Restart the tunnel service

```powershell
net stop Cloudflared
net start Cloudflared
```

### Step 4: Verify

```powershell
curl https://newapp.quickautotags.com/health
```

That's it. The new app is live with HTTPS.

---

## Connecting a Claude Managed Agent

Any app exposed through this tunnel can be whitelisted in the managed agent's environment config:

```json
{
  "type": "cloud",
  "networking": {
    "type": "limited",
    "allowed_hosts": [
      "hub.quickautotags.com",
      "newapp.quickautotags.com"
    ],
    "allow_mcp_servers": true,
    "allow_package_managers": true
  }
}
```

The `allowed_hosts` field only accepts **domain names** — raw IP:port (e.g., `38.247.188.233:8100`) is not supported. This is why the tunnel is required.

---

## Useful Commands

```powershell
# Check tunnel status
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel info qat-hub

# List all tunnels
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel list

# Add DNS for a new subdomain
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel route dns qat-hub newapp.quickautotags.com

# Restart tunnel service
net stop Cloudflared && net start Cloudflared

# Run tunnel in foreground (for debugging)
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel run qat-hub

# Check Windows service status
sc query Cloudflared
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Tunnel not starting | Check `config.yml` syntax — YAML is whitespace-sensitive |
| DNS not resolving | Run `tunnel route dns` command again, check Cloudflare dashboard for CNAME |
| App unreachable through tunnel | Make sure the local app is running on the correct port |
| Certificate errors | The cert at `~/.cloudflared/cert.pem` may have expired — run `cloudflared tunnel login` again |
| Service won't restart | Check Windows Event Viewer > Application logs for cloudflared errors |

---

## Architecture Diagram

```
Internet                Cloudflare Edge           VPS (38.247.188.233)
────────                ───────────────           ────────────────────

Browser/Agent  ──HTTPS──>  Cloudflare   <──QUIC──  cloudflared service
                          (SSL termination)              │
                          hub.quickautotags.com          ├── localhost:8100 (QAT Hub)
                          app2.quickautotags.com         ├── localhost:XXXX (Future App)
                          ...                            └── ...
```

The tunnel is **outbound-only** from the VPS — no firewall ports need to be opened at DatabaseMart.
