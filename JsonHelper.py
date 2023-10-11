def json_get_or_default(target, value, default=None):
    if value in target:
        return target[value]
    
    return default

def json_get_or_fail(target, value, hint=None):
    if value in target:
        return target[value]
    
    if hint is not None:
        hint = " " + hint
    else:
        hint = ""
    raise Exception(f"key '{value}' not found in json element{hint}")