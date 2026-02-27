import importlib.resources
import subprocess


def main():
    perl_script = importlib.resources.files("replan_central.perl") / "get_web_content.pl"
    subprocess.run(["perl", str(perl_script)], check=True)
