"""Local skills. Each skill is one module under this package and shares skills.host.

To add a skill: write skills/<name>.py, call registry.register(Skill(...)) at import,
and import that module from registry.load(). The chat checkbox list comes from listed().
"""

from skills.registry import get, listed, load, register, selected

__all__ = ["get", "listed", "load", "register", "selected"]
