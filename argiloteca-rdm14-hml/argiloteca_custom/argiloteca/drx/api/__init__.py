"""Read-only route modules for the public Argiloteca blueprint."""

from .blueprint import DrxReadDependencies, create_drx_blueprint

__all__ = ["DrxReadDependencies", "create_drx_blueprint"]
