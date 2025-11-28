"""
Mutmut configuration for ModemCheck Cloud Server.

This file configures mutation testing to focus on critical code paths
while skipping test files and non-critical modules.
"""


def pre_mutation(context):
    """Skip files that shouldn't be mutated."""
    # Skip test files
    if context.filename.startswith("tests/"):
        context.skip = True
        return

    # Skip migrations
    if "migrations" in context.filename:
        context.skip = True
        return

    # Skip __init__.py files (usually just imports)
    if context.filename.endswith("__init__.py"):
        context.skip = True
        return

    # Skip main.py (application entry point)
    if context.filename.endswith("main.py"):
        context.skip = True
        return


def init():
    """Initialize mutmut settings."""
    pass
