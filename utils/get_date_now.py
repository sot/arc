"""Convert the now_date from timeline_states.js to a CxoTime date string."""

import json
import sys
from pathlib import Path

from cxotime import CxoTime

data_dir = sys.argv[1]
text = Path(f"{data_dir}/timeline_states.js").read_text()
data = json.loads(text[11:])

# Get date like "319/1215z"
now_date = data["now_date"]
year = CxoTime.now().date[:4]

# Convert now_date to "{year}:319:12:15:00"
date = f"{year}:{now_date[0:3]}:{now_date[4:6]}:{now_date[6:8]}:00"
print(date)
