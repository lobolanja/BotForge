from .auth import login, login_disabled, logout, start, status
from .auth_guard import require_login
from .greet import greet
from .help import help_command
from .ping import ping
from .time import time
from .translate import translate
from .unknown import unknown_command

# Re-export command handlers from one place so main.py can stay compact.
__all__ = [
    "greet",
    "help_command",
    "login",
    "login_disabled",
    "logout",
    "ping",
    "require_login",
    "start",
    "status",
    "time",
    "translate",
    "unknown_command",
]
