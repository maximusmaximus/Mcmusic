# PlanetaryExplorer A2A (Agent2Agent) Tailscale Service

## Overview
The primary Windows workstation (`PlanetaryExplorer`) exposes an authenticated A2A (Agent2Agent) server exclusively over the Tailscale network.
Other Antigravity machines, remote agent nodes, and subagents on the Tailscale mesh should use this service to delegate tasks, offload processing, or coordinate distributed workflows.

## Connection Details
- **Tailscale IPv4**: `100.125.60.37`
- **Tailscale Port**: `8080`
- **MagicDNS URL**: `http://planetaryexplorer.tail24df4e.ts.net:8080`
- **Direct IP URL**: `http://100.125.60.37:8080`
- **Agent Card**: `http://planetaryexplorer.tail24df4e.ts.net:8080/.well-known/agent-card.json`
- **REST Message Endpoint**: `http://planetaryexplorer.tail24df4e.ts.net:8080/a2a/v1/message`
- **JSON-RPC 2.0 Endpoint**: `http://planetaryexplorer.tail24df4e.ts.net:8080/a2a/v1/rpc`
- **Health Endpoint**: `http://planetaryexplorer.tail24df4e.ts.net:8080/health`
- **Auth Scheme**: `Bearer 2u6GZL1hOE_3TPrByRzdndMsxwUGwJF3lYDbm6HEzME`

## When to Direct Tasks to This Node
Direct tasks to PlanetaryExplorer when:
1. **Windows-Native Work**: Work requiring Windows PowerShell, Windows Media Foundation (`h264_mf`), direct Windows audio device access, or local Windows file paths (`D:\music\...`).
2. **Heavy GPU/Video Rendering**: High-performance local rendering, motion graphics, or video generation pipelines.
3. **Cross-Agent Task Delegation**: Routing subtasks between Linux nodes (e.g. `mcclaw-ubuntu`, `molt`, `raspberrypi`) and the Windows workstation.

## How to Call the Service

### 1. Python (via `skills/a2a-client/scripts/a2a_call.py`)
```bash
python skills/a2a-client/scripts/a2a_call.py --message "Process audio task" --sender "remote-agent-01"
```

### 2. cURL / REST
```bash
curl -X POST http://planetaryexplorer.tail24df4e.ts.net:8080/a2a/v1/message \
  -H "Authorization: Bearer 2u6GZL1hOE_3TPrByRzdndMsxwUGwJF3lYDbm6HEzME" \
  -H "Content-Type: application/json" \
  -d '{"message": "Task description here", "sender": "agent-node"}'
```

### 3. JSON-RPC 2.0
```bash
curl -X POST http://planetaryexplorer.tail24df4e.ts.net:8080/a2a/v1/rpc \
  -H "Authorization: Bearer 2u6GZL1hOE_3TPrByRzdndMsxwUGwJF3lYDbm6HEzME" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "delegate", "params": {"task": "execute_workflow"}}'
```
