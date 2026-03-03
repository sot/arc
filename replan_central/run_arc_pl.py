import subprocess
import argparse
import importlib.resources

def main():
    parser = argparse.ArgumentParser(description="Run arc.pl Perl script")
    parser.add_argument("--out", required=True, help="Output directory for Perl script")
    parser.add_argument("--data-dir", required=True, help="Data directory for Perl script")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--config", help="Config file name (arc3, arc_ops, etc)")
    args = parser.parse_args()

    perl_script = importlib.resources.files("replan_central.perl") / "arc.pl"
    cmd = ["perl", perl_script, "--out", args.out, "--data_dir", args.data_dir]
    if args.debug:
        cmd.append("--debug")
    if args.config:
        cmd.extend(["--config", args.config])
    subprocess.run(cmd, check=True)
