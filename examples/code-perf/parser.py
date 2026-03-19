"""Fast JSON parser facade.

The public API stays as ``parse(text: str)`` but delegates to the stdlib
decoder, which is substantially faster than a handwritten Python parser while
matching ``json.loads()`` semantics for supported inputs.
"""

from json import JSONDecodeError, JSONDecoder


parse = JSONDecoder().decode

