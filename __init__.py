WEB_DIRECTORY = "./js"
PLUGIN_VERSION = "0.1.0"

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from .routes import register_routes

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
    "PLUGIN_VERSION",
]

register_routes()