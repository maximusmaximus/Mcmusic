-- init_session.lua
local utils = dofile("/opt/dawagent/lua/utils.lua")

if not Session then 
  utils.json_error("No active session.")
  return
end

print("Session initialized: " .. Session:name())
Session:request_save()
utils.json_success()
