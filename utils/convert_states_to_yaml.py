"""Convert timeline_states.js to YAML timeline_states.yaml for easier comparison."""

import json
import sys
from pathlib import Path

import yaml

data_dir = sys.argv[1]
text = Path(f"{data_dir}/timeline_states.js").read_text()
states = json.loads(text[11:])
yaml.dump(states, open(f"{data_dir}/timeline_states.yaml", "w"))
