#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys


def main() -> None:
    """Run a Django management command from the command line."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    # The suite must not inherit a developer's .env: DEBUG changes how Django
    # answers an error, and .env is untracked, so a run on one machine would
    # quietly stop meaning what a run on another means. Set before settings is
    # imported, which is where load_dotenv leaves an already-set variable
    # alone. `manage.py test --debug-mode` still turns it on deliberately.
    if sys.argv[1:2] == ["test"]:
        os.environ.setdefault("DJANGO_DEBUG", "0")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django could not be imported. Is it installed and is the virtual "
            "environment activated? Install it with: pip install -r requirements.txt"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
