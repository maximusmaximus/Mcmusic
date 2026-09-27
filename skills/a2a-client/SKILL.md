---
name: a2a-client
description: Send tasks, queries, and instructions to the PlanetaryExplorer A2A (Agent2Agent) server over Tailscale. Use when needing to delegate work to the Windows workstation or coordinate cross-agent activities.
---

# A2A Client Skill

Delegates tasks and exchanges structured agent messages with the `PlanetaryExplorer` A2A node running over Tailscale.

## Node Specifications
- **Host**: `planetaryexplorer.tail24df4e.ts.net` / `100.125.60.37`
- **Port**: `8080`
- **Bearer Token**: Set via environment variable `A2A_AUTH_TOKEN` or `config.yaml`

## Usage

### CLI Task Dispatch
```bash
python scripts/a2a_call.py --message "Execute release pack verification" --sender "hermes-agent"
```

### Check Node Status
```bash
python scripts/a2a_call.py --status
```

### Python Programmatic Usage
```python
from a2a_call import A2AClient

client = A2AClient()
res = client.send_message("Master track verification", sender="dawagent")
print(res)
```
