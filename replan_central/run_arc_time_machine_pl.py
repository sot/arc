import argparse
import importlib.resources
import subprocess


def main():
    parser = argparse.ArgumentParser(description="Run arc_time_machine.pl Perl script")
    parser.add_argument(
        "--arc-data-dir", dest="arc_data_dir", help="ARC data directory"
    )
    parser.add_argument(
        "--time-machine-dir", dest="time_machine_dir", help="Time machine directory"
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    args, unknown = parser.parse_known_args()

    perl_script = (
        importlib.resources.files("replan_central.perl") / "arc_time_machine.pl"
    )
    cmd = [
        "perl",
        str(perl_script),
        "--arc-data-dir",
        args.arc_data_dir,
        "--time-machine-dir",
        args.time_machine_dir,
    ]
    if args.verbose:
        cmd.append("--verbose")
    subprocess.run(cmd, check=True)
