#!/usr/bin/env python

import os
import sys
import requests
import argparse
import tables
import time

import numpy as np
from astropy.table import Table
from Chandra.Time import DateTime

parser = argparse.ArgumentParser(description='Archive GOES data and '
                                 'HRC shield rate proxy')
parser.add_argument('--data-dir', type=str,
                    default='.',
                    help='Directory for output data files')
args = parser.parse_args()

url = 'https://services.swpc.noaa.gov/json/goes/primary/differential-protons-6-hour.json'

last_err = None
for _ in range(3):
    try:
        json_file = requests.get(url)
        data = json_file.json()
        break
    except Exception as err:
        last_err = err
        time.sleep(5)
else:
    print(f'Warning: failed to open URL {url}: {last_err}')
    sys.exit(0)

dat = Table(data)

secs = []
for row in dat:
    sec = DateTime(row['time_tag'][:-1], format='fits').secs
    secs.append(sec)
dat['time'] = secs

descrs = [('time', 'f8'), ('hrc_shield', 'f8')]
channels = ['P1', 'P2A', 'P2B', 'P3', 'P4', 'P5', 'P6',
            'P7', 'P8A', 'P8B', 'P8C', 'P9', 'P10']

tabs = []
for channel in channels:
    ok = dat['channel'] == channel
    t = dat[ok]
    t.rename_column('flux', channel)
    tabs.append(t)
    descrs.append((channel, 'f8'))

newdat = np.ndarray(len(tabs[0]), dtype=descrs)
newdat['time'] = tabs[0]['time']

for t in tabs:
    if not all(t['time'] == newdat['time']):
        print(f'Warning: mismatch in channel time column')
        sys.exit(0)
    else:
        for col in t.colnames:
            if col in channels:
                newdat[col] = t[col]

# TBD
hrc_shield = (6000 * newdat['P5'] + 270000 * newdat['P7']
              + 100000 * newdat['P9']) / 256.
hrc_bad = (newdat['P5'] < 0) | (newdat['P7'] < 0) | (newdat['P9'] < 0)

newdat['hrc_shield'] = hrc_shield
newdat['hrc_shield'][hrc_bad] = -1.0e5  # flag bad inputs

os.chdir(args.data_dir)


# WIP
h5 = tables.open_file('hrc_shield.h5', mode='a',
                     filters=tables.Filters(complevel=5, complib='zlib'))
try:
    table = h5.root.data
    lasttime = table.col('time')[-1]
    ok = newdat['time'] > lasttime
    h5.root.data.append(newdat[ok])
except tables.NoSuchNodeError:
    table = h5.create_table(h5.root, 'data', newdat,
                           "HRC Antico shield + GOES", expectedrows=2e7)
h5.root.data.flush()
h5.close()

# Also write the mean of the last three values (15 minutes) to
# hrc_shield.dat.  Only include good values.
times = DateTime(newdat['time'][-3:]).unix
hrc_shield = hrc_shield[-3:]
ok = ~hrc_bad[-3:]
if len(hrc_shield[ok]) > 0:
    with open('hrc_shield.dat', 'w') as f:
        print(hrc_shield[ok].mean(), times[ok].mean(), file=f)

for colname, scale, filename in zip(
    ('p2', 'p5'), (3.3, 12.0), ('p4gm.dat', 'p41gm.dat')):
    proxy = dat[colname][-3:] * scale
    ok = proxy > 0
    if len(proxy[ok]) > 0:
        with open(filename, 'w') as f:
            print(proxy[ok].mean(), times[ok].mean(), file=f)
