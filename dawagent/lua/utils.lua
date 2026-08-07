return {
  find_track = function(name)
    for t in Session:get_tracks():iter() do
      if t:name() == name then return t end
    end
    return nil
  end,
  
  json_success = function(data)
    print('{"success": true, "message": "Operation completed"}')
  end,
  
  json_error = function(msg)
    print('{"success": false, "error": "' .. msg .. '"}')
  end
}
