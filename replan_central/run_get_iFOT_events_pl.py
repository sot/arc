
import os
import sys
import subprocess
import importlib.resources
import argparse

def main():
    parser = argparse.ArgumentParser(description="Run get_iFOT_events.pl Perl script")
    parser.add_argument("--output-dir", required=True, help="Output directory for Perl script")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    perl_script = importlib.resources.files("replan_central.perl") / "get_iFOT_events.pl"
    cmd = ["perl", str(perl_script), "--output-dir", args.output_dir]
    if args.debug:
        cmd.append("--debug")
    subprocess.run(cmd, check=True)
