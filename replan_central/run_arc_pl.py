import os
import subprocess


def main():
    perl_script = os.path.join(os.path.dirname(__file__), "../perl/arc.pl")
    subprocess.run(["perl", perl_script], check=True)
