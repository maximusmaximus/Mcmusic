-- write_automation.lua
local utils = dofile("/opt/dawagent/lua/utils.lua")

local track_name = arg[1]
if not track_name then
  utils.json_error("Usage: write_automation.lua <track_name>")
  return
end

local t = utils.find_track(track_name)
if not t then
  utils.json_error("Track not found")
  return
end

-- Example automation setup
local al = t:automation_control(ARDOUR.AutomationType.GainAutomation, false)
if al then
  al:set_automation_state(ARDOUR.AutoState.Play)
end

Session:request_save()
utils.json_success()
