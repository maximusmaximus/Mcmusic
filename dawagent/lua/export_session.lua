-- export_session.lua — Export Ardour session to audio file
-- Usage: ardour8-lua export_session.lua <session_path> [format] [output_dir]
--
-- Requires a running Ardour session loaded via ardour8-lua.
-- Falls back to the session's default export format if none specified.

local utils = dofile("/opt/dawagent/lua/utils.lua")

local format = arg[1] or "wav"
local out_dir = arg[2] or "/opt/dawagent/exports"

if not Session then
  utils.json_error("No active Ardour session — run via ardour8-lua with a session loaded")
  return
end

-- Get session info
local session_name = Session:name()
local sr = Session:nominal_sample_rate()
local session_end = Session:current_end_sample()

if session_end == 0 then
  utils.json_error("Session is empty (0 length)")
  return
end

print(string.format("[export] Session: %s | SR: %d | Length: %d samples", session_name, sr, session_end))

-- Use Ardour's built-in export functionality
local export_handler = Session:get_export_handler()
if not export_handler then
  utils.json_error("Failed to get export handler from session")
  return
end

local export_status = Session:get_export_status()

-- Configure export: use the session's default timespan (full session)
local timespans = export_handler:get_timespans()
local channel_configs = export_handler:get_channel_configs()
local format_specs = export_handler:get_formats()

if not timespans or not channel_configs or not format_specs then
  -- Fallback: set up a basic export range covering the full session
  print("[export] Setting up full-session export range")

  -- Create timespan for full session
  local ts = export_handler:add_timespan()
  if ts then
    ts:set_range(0, session_end)
    ts:set_name(session_name)
  end
end

-- Set output directory
export_handler:set_export_dir(out_dir)

-- Run the export
local ok = export_handler:do_export()
if ok then
  print(string.format("[export] ✓ Export complete: %s → %s", session_name, out_dir))
  utils.json_success()
else
  utils.json_error("Export failed — check Ardour logs for details")
end
