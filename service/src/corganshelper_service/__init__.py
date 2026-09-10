"""The local service behind the corganshelper extension."""

# Mirrors package.json; scripts/bump_version.py writes it, hatchling reads
# it as the package version. It lives here and not in pyproject.toml so that
# a bump does not date uv.lock, which pins the project's own version too.
__version__ = "0.1.32"
