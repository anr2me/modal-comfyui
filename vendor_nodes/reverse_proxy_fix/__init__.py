"""Let ComfyUI save workflows when Modal's proxy decodes %2F in userdata paths.

ComfyUI registers POST/DELETE ``/userdata/{file}`` for a single path segment,
and its frontend percent-encodes the slash so ``workflows/foo.json`` travels as
``workflows%2Ffoo.json``. Modal's edge proxy decodes that ``%2F`` back to ``/``
before ComfyUI sees it, so the path gains a segment, the single-segment routes
stop matching, and saving fails with HTTP 405.

Fix: after ComfyUI registers its routes, register the same userdata handlers
under a slash-tolerant ``{file:.+}`` pattern so the decoded paths resolve to
them. ComfyUI's handlers validate the path (``abspath`` + ``commonpath``), so a
captured value containing ``/`` still cannot escape the user directory.
"""

from server import PromptServer

_SUFFIX = "/userdata/{file}"
_METHODS = ("POST", "DELETE")


def _register_slash_tolerant_userdata(app):
    additions = []
    for route in app.router.routes():
        resource = route.resource
        if resource is None or route.method not in _METHODS:
            continue
        canonical = resource.canonical  # "/userdata/{file}" or "/api/userdata/{file}"
        if canonical.endswith(_SUFFIX):
            tolerant = canonical[: -len("{file}")] + "{file:.+}"
            additions.append((route.method, tolerant, route.handler))
    for method, path, handler in additions:
        app.router.add_route(method, path, handler)


_original_add_routes = PromptServer.add_routes


def _add_routes(self):
    result = _original_add_routes(self)
    _register_slash_tolerant_userdata(self.app)
    return result


PromptServer.add_routes = _add_routes

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
