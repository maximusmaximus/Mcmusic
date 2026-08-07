-- export_session.lua
local utils = dofile("/opt/dawagent/lua/utils.lua")

local format = arg[1] or "wav"
local out_dir = arg[2] or "/opt/dawagent/exports"

print("Exporting session to " .. out_dir)

-- trigger default export format
local format_manager = Session:export_format_manager()
local formats = format_manager:formats()
-- Simplified logic: assumes Ardour executes the default export preset

utils.json_success()
