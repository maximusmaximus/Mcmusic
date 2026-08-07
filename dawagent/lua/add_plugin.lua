-- add_plugin.lua
local utils = dofile("/opt/dawagent/lua/utils.lua")

local track_name = arg[1]
local plugin_uri = arg[2]

if not track_name or not plugin_uri then
  utils.json_error("Usage: add_plugin.lua <track_name> <plugin_uri>")
  return
end

local t = utils.find_track(track_name)
if not t then
  utils.json_error("Track not found: " .. track_name)
  return
end

-- Add plugin logic
local plugin = ARDOUR.LuaAPI.new_plugin(Session, plugin_uri, ARDOUR.PluginType.LV2, "")
if not plugin then
  utils.json_error("Failed to load plugin: " .. plugin_uri)
  return
end

t:add_processor_by_index(plugin, 0, nil, true)
Session:request_save()
utils.json_success()
