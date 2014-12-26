#!/usr/bin/env python
import os
import shutil
import argparse

ARC_DIR = os.path.join(os.environ['SKA'], 'data', 'arc')
ACE_RATES_FILE = '/data/mta4/www/ace.html'

parser = argparse.ArgumentParser(description='Get mta ace.html')
parser.add_argument("--data-dir",
                    default=ARC_DIR)
args = parser.parse_args()

lines = [line for line in open(ACE_RATES_FILE, 'r')
         if line.startswith('AVERAGE   ')]
# Do nothing unless there is one AVERAGE line
if len(lines) == 1:
    shutil.copy2(ACE_RATES_FILE, args.data_dir)

