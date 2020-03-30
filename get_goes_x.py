#!/usr/bin/env python
# Licensed under a 3-clause BSD style license - see LICENSE.rst
"""
Fetch GOES X-ray data and update h5 table
"""

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
                    default='GOES_X.h5',
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
times = Time(joindat['time_tag'])
joindat['time'] = times.cxcsec
joindat.remove_column('time_tag')

# Add the other columns the old file format wanted
joindat['mjd'] = times.mjd.astype(int)
joindat['secs'] = np.array(np.round((times.mjd - joindat['mjd']) * 86400,
                                    decimals=0)).astype(int)
joindat['year'] = [t.year for t in times.datetime]
joindat['month'] = [t.month for t in times.datetime]
joindat['dom'] = [t.day for t in times.datetime]
joindat['hhmm'] = np.array([f"{t.hour}{t.minute}" for t in times.datetime]).astype(int)

joindat['ratio'] = -100000.0
ok = (joindat['long'] != 0) & (joindat['long'] != -100000.0)
joindat['ratio'][ok] = joindat['short'][ok] / joindat['long'][ok]

# Save to h5
joindat['satellite'] = args.satellite
newdat = joindat['year', 'month', 'dom', 'hhmm', 'mjd', 'secs',
                'short', 'long', 'ratio', 'time', 'satellite'].as_array()

with tables.open_file(args.h5, mode='a',
                      filters=tables.Filters(complevel=5, complib='zlib')) as h5:
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

