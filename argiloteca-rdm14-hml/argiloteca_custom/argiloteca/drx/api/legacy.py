from flask import request


def bounded_int_arg(name, default, minimum=1, maximum=250):
    """Compatibility parser matching the historical views.py behavior."""
    try:
        value = int(request.args.get(name) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))
