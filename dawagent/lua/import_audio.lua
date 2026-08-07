-- import_audio.lua
local utils = dofile("/opt/dawagent/lua/utils.lua")

local file_path = arg[1]
local track_name = arg[2]

if not file_path or not track_name then
  utils.json_error("Usage: import_audio.lua <file_path> <track_name>")
  return
end

local t = utils.find_track(track_name)
if not t then
  utils.json_error("Track not found: " .. track_name)
  return
end

-- Ardour 8 import API
local pos = Session:transport_sample()
local import_status = Session:import_audio(file_path, t, pos)
Session:request_save()
utils.json_success()
