"""Entry point for the ssh-emmc medium of avocado-flash."""

import sys
from typing import List


def main(argv: List[str]) -> int:
    """Run the ssh-emmc medium; argv is everything after the `ssh-emmc` word."""
    print("avocado-flash: the ssh-emmc medium is not implemented yet", file=sys.stderr)
    return 2
