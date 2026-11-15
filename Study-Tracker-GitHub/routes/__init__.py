"""HTTP handlers grouped by feature."""
from . import study, reports, profile, journal, timer


def register_routes(app):
    for module in (study, reports, profile, journal, timer):
        module.register_routes(app)
