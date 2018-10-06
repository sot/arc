#!/usr/bin/env python

import os
import sys
import urllib.request, urllib.error, urllib.parse
import argparse
import tables
import time

import numpy as np
from astropy.io import ascii
from Chandra.Time import DateTime

parser = argparse.ArgumentParser(description='Archive GOES data and '
                                 'HRC shield rate proxy')
parser.add_argument('--data-dir', type=str,
                    default='.',
                    help='Directory for output data files')
args = parser.parse_args()

url = 'ftp://ftp.swpc.noaa.gov/pub/lists/pchan/Gp_pchan_5m.txt'
colnames = ('year month dom  hhmm  mjd secs p1  p2  p3 '
            'p4  p5  p6  p7  p8  p9 p10 p11').split()

for _ in range(3):
    try:
        urlob = urllib.request.urlopen(url)
        urldat = urlob.read().decode()
        break
    except Exception as err:
        time.sleep(5)
else:
    print('Warning: failed to open URL {}: {}'.format(url, err))
    sys.exit(0)

dat = ascii.read(urldat, Reader=ascii.NoHeader, names=colnames,
                 data_start=3)
hrc_bad = (dat['p4'] < 0) | (dat['p5'] < 0) | (dat['p6'] < 0)

mjd = dat['mjd'] + dat['secs'] / 86400.

secs = DateTime(mjd, format='mjd').secs

hrc_shield = (6000 * dat['p4'] + 270000 * dat['p5']
              + 100000 * dat['p6']) / 256.

descrs = dat.dtype.descr
descrs.append(('hrc_shield', 'f8'))
descrs.append(('time', 'f8'))
newdat = np.ndarray(len(dat), dtype=descrs)
for colname in colnames:
    newdat[colname] = dat[colname]
newdat['hrc_shield'] = hrc_shield
newdat['hrc_shield'][hrc_bad] = -1.0e5  # flag bad inputs
newdat['time'] = secs

os.chdir(args.data_dir)

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
