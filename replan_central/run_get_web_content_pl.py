import argparse
import importlib.resources
import subprocess


def main():
    parser = argparse.ArgumentParser(description="Run get_web_content.pl Perl script")
    parser.add_argument("--out", required=True, help="Output directory for Perl script")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    perl_script = (
        importlib.resources.files("replan_central.perl") / "get_web_content.pl"
    )
    cmd = ["perl", str(perl_script), "--out", args.out]
    if args.debug:
        cmd.append("--debug")
    subprocess.run(cmd, check=True)
