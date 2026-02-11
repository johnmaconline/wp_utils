##########################################################################################
#
# Script name: wp_utilities.py
#
# Description: Wrapper that re-exports tools.wp_utilities for compatibility.
#
##########################################################################################

import sys
from tools import wp_utilities as _impl

# Expose the implementation module directly so attribute monkeypatching on
# `wp_utilities` affects function globals defined in `tools.wp_utilities`.
if __name__ != '__main__':
    sys.modules[__name__] = _impl

if __name__ == '__main__':
    from tools.wp_utilities import main as _main

    _main()
