#!/usr/bin/env python

import sys
import urllib.request, urllib.error, urllib.parse
import argparse
import tables
import time
import json

import numpy as np
from astropy.io import ascii
from astropy.table import Table, join
from Chandra.Time import DateTime

parser = argparse.ArgumentParser(description='Get GOES_X data')
parser.add_argument('--h5',
                    default='GOES_X_16.h5',
                    help='HDF5 file name')
args = parser.parse_args()

url = 'https://services.swpc.noaa.gov/json/goes/primary/xrays-3-day.json'

last_err = None
for _ in range(3):
    try:
        urlob = urllib.request.urlopen(url)
        urldat = urlob.read().decode()
        break
    except Exception as err:
        last_err = err
        time.sleep(5)
else:
    print(('Warning: failed to open URL {}: {}'.format(url, last_err)))
    sys.exit(0)

try:
    dat = Table(json.loads(urldat))
except Exception as err:
    print(('Warning: malformed GOES_X data so table read failed: {}'
          .format(err)))
    sys.exit(0)

# Select only the GOES 16 data (which is all there is)
dat = dat[dat['satellite'] == 16]
# Make a table for each of the two wavelengths
shortdat = dat[dat['energy'] == '0.05-0.4nm']['flux', 'time_tag']
shortdat.rename_column('flux', 'short_flux')
longdat = dat[dat['energy'] == '0.1-0.8nm']['flux', 'time_tag']
longdat.rename_column('flux', 'long_flux')
# Join them on time (seems to be OK for these data)
joindat = join(shortdat, longdat)

# Add a time column with Chandra secs
secs = []
for row in joindat:
    secs.append(DateTime(row['time_tag'].strip('Z')).secs)
joindat['time'] = secs
joindat.remove_column('time_tag')

# Save to h5
newdat = joindat.as_array()

h5 = tables.open_file(args.h5, mode='a',
                     filters=tables.Filters(complevel=5, complib='zlib'))
try:
    table = h5.root.data
    lasttime = table.col('time')[-1]
    ok = newdat['time'] > lasttime
    newdat = newdat[ok]
    h5.root.data.append(newdat)
except tables.NoSuchNodeError:
    table = h5.create_table(h5.root, 'data', newdat,
                           "GOES_X rates", expectedrows=2e7)
h5.root.data.flush()
h5.close()
