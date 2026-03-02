#!/usr/bin/env python3
import subprocess
import sys
import os

# Get the path to arc_time_machine.pl
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PERL_SCRIPT = os.path.join(SCRIPT_DIR, "perl", "arc_time_machine.pl")

# Pass all arguments to the Perl script
args = ["perl", PERL_SCRIPT] + sys.argv[1:]

try:
    result = subprocess.run(args, check=True)
    sys.exit(result.returncode)
except subprocess.CalledProcessError as e:
    print(f"Error running arc_time_machine.pl: {e}", file=sys.stderr)
    sys.exit(e.returncode)
