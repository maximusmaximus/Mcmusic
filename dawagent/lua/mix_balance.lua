-- mix_balance.lua
local utils = dofile("/opt/dawagent/lua/utils.lua")

local track_name = arg[1]
local fader_val = tonumber(arg[2]) -- gain coefficient or dB
local pan_val = tonumber(arg[3]) -- 0 to 1

if not track_name or not fader_val then
  utils.json_error("Usage: mix_balance.lua <track_name> <fader_val> [pan_val]")
  return
end

local t = utils.find_track(track_name)
if not t then
  utils.json_error("Track not found: " .. track_name)
  return
end

t:gain_control():set_value(fader_val, ARDOUR.Controllable.NoGroup)
if pan_val then
  local panner = t:pan_azimuth_control()
  if panner then panner:set_value(pan_val, ARDOUR.Controllable.NoGroup) end
end

Session:request_save()
utils.json_success()
