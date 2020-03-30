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
from astropy.time import Time

parser = argparse.ArgumentParser(description='Get GOES_X data')
parser.add_argument('--h5',
                    default='GOES_X_16.h5',
                    help='HDF5 file name')
parser.add_argument('--satellite',
                    default=16,
                    type=int,
                    help='Select which satelite from the json file by int id')
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

# Select only the GOES satellite specified from the args
dat = dat[dat['satellite'] == args.satellite]
if len(dat) == 0:
    print('Warning: No data in fetched file for satellite {}'.format(args.satellite))
    sys.exit(0)

# Make a table for each of the two wavelengths
shortdat = dat[dat['energy'] == '0.05-0.4nm']['flux', 'time_tag']
shortdat.rename_column('flux', 'short')
longdat = dat[dat['energy'] == '0.1-0.8nm']['flux', 'time_tag']
longdat.rename_column('flux', 'long')
if len(longdat) != len(shortdat):
    print('Warning: "short" and "long" table have mismatched lengths')

# Join them on time (seems to be OK for these data)
joindat = join(shortdat, longdat)

# Add a time column with Chandra secs and remove original time_tags
joindat['time'] = Time(joindat['time_tag']).cxcsec
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
