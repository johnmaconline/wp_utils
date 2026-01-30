##########################################################################################
#
# Script name: wp_utilities.py
#
# Description: Wrapper that re-exports tools.wp_utilities for compatibility.
#
##########################################################################################

from tools.wp_utilities import *  # noqa: F401,F403


if __name__ == '__main__':
    from tools.wp_utilities import main as _main

    _main()
