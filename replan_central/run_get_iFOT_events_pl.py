import os
import subprocess
import importlib.resources


def main():
    perl_script = importlib.resources.files("replan_central.perl") / "get_iFOT_events.pl"
    subprocess.run(["perl", str(perl_script)], check=True)
