"""
QAT Operations Hub — Managed Agent Setup Script

One-time script to create the managed agent and environment
via the Anthropic API. Run once, then use the saved IDs.

Usage:
    python scripts/setup_managed_agent.py

Requires:
    - ANTHROPIC_API_KEY in environment or .env
    - pip install anthropic
"""

import json
import os
import sys
from pathlib import Path

# Load .env if present
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip()
                if value and not os.environ.get(key):
                    os.environ[key] = value

try:
    import anthropic
except ImportError:
    print("ERROR: anthropic package not installed. Run: pip install anthropic")
    sys.exit(1)

API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not API_KEY:
    print("ERROR: ANTHROPIC_API_KEY not set in environment or .env")
    sys.exit(1)

client = anthropic.Anthropic(api_key=API_KEY)

HUB_DOMAIN = "hub.quickautotags.com"

print(f"Setting up QAT Operations managed agent...")
print(f"Hub domain: {HUB_DOMAIN}")
print()

# --- Step 1: Create environment ---
print("[1/3] Creating environment with networking config...")
try:
    environment = client.beta.environments.create(
        name="qat-production",
        config={
            "type": "cloud",
            "networking": {
                "type": "limited",
                "allowed_hosts": [HUB_DOMAIN],
                "allow_mcp_servers": True,
                "allow_package_managers": True,
            },
        },
    )
    print(f"  Environment ID: {environment.id}")
except Exception as e:
    print(f"  ERROR creating environment: {e}")
    print("  If the API doesn't support this yet, you may need to configure")
    print("  networking through the Anthropic Console or contact support.")
    sys.exit(1)

# --- Step 2: Create agent ---
print("[2/3] Creating managed agent...")
try:
    agent = client.beta.agents.create(
        name="QAT Operations Agent",
        model="claude-sonnet-4-6",
        system=f"""You are the QAT Operations Agent for Quick Auto Tags (Mata Enterprises, Inc.),
a California DMV-licensed vehicle tag and title agency.

You trigger and monitor CRM enrichment runs via the QAT Operations Hub API.

Hub base URL: https://{HUB_DOMAIN}

Available endpoints:
- GET /health — health check, returns {{"status": "healthy", ...}}
- GET /status — module status and metrics
- POST /run/crm_enrichment — trigger CRM enrichment run

When asked to run enrichment, call POST /run/crm_enrichment with JSON body:
{{"dry_run": false, "target_year": 2025, "target_month": 1}}

Adjust target_month as needed (1=Jan, 2=Feb, etc.).

Workflow:
1. Always check /health first to confirm the Hub is online
2. Check /status to see current module state
3. Trigger runs as requested
4. Report results back to the user clearly

If the Hub is down or unreachable, inform the user immediately.""",
        tools=[{"type": "agent_toolset_20260401"}],
    )
    print(f"  Agent ID: {agent.id}")
    print(f"  Agent Version: {agent.version}")
except Exception as e:
    print(f"  ERROR creating agent: {e}")
    sys.exit(1)

# --- Step 3: Save config ---
print("[3/3] Saving configuration...")
config_path = Path(__file__).resolve().parent / "agent_config.json"
config_data = {
    "environment_id": environment.id,
    "agent_id": agent.id,
    "agent_version": agent.version,
    "hub_domain": HUB_DOMAIN,
    "hub_url": f"https://{HUB_DOMAIN}",
}
with open(config_path, "w") as f:
    json.dump(config_data, f, indent=2)

print(f"  Saved to: {config_path}")
print()
print("=" * 60)
print("Setup complete!")
print()
print(f"  Environment ID: {environment.id}")
print(f"  Agent ID:       {agent.id}")
print(f"  Hub URL:        https://{HUB_DOMAIN}")
print()
print("To create a session and interact with the agent,")
print("use these IDs with the Anthropic sessions API.")
print("=" * 60)
