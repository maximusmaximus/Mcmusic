return {
  find_track = function(name)
    for t in Session:get_tracks():iter() do
      if t:name() == name then return t end
    end
    return nil
  end,
  
  json_success = function(data)
    if data then
      print('{"success": true, "message": "Operation completed", "data": ' .. data .. '}')
    else
      print('{"success": true, "message": "Operation completed"}')
    end
  end,
  
  json_error = function(msg)
    -- Escape quotes and backslashes to prevent JSON injection
    local safe = msg:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', '\\n')
    print('{"success": false, "error": "' .. safe .. '"}')
  end
}
