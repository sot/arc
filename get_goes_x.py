#!/usr/bin/env python

import sys
import urllib2
import argparse
import tables
import time

import numpy as np
from astropy.io import ascii
from Chandra.Time import DateTime

parser = argparse.ArgumentParser(description='Get GOES_X data')
parser.add_argument('--h5',
                    default='GOES_X.h5',
                    help='HDF5 file name')
args = parser.parse_args()

url = 'http://www.swpc.noaa.gov/ftpdir/lists/xray/Gp_xr_5m.txt'

for _ in range(3):
    try:
        urlob = urllib2.urlopen(url)
        urldat = urlob.read()
        break
    except Exception as err:
        time.sleep(5)
else:
    print 'Warning: failed to open URL {}: {}'.format(url, err)
    sys.exit(0)

colnames = 'year month dom  hhmm  mjd secs short long ratio'.split()
data_colnames = colnames[-3:]

try:
    dat = ascii.read(urldat, guess=False, Reader=ascii.NoHeader,
                     data_start=3, names=colnames)
except Exception as err:
    print('Warning: malformed GOES_X data so table read failed: {}'
          .format(err))
    sys.exit(0)

# Strip up to two rows at the end if any values are bad (i.e. negative)
for _ in range(2):
    if any(dat[name][-1] < 0 for name in data_colnames):
        dat = dat[:-1]

mjd = dat['mjd'] + dat['secs'] / 86400.

secs = DateTime(mjd, format='mjd').secs

descrs = dat.dtype.descr
descrs.append(('time', 'f8'))
newdat = np.ndarray(len(dat), dtype=descrs)
for colname in colnames:
    newdat[colname] = dat[colname]
newdat['time'] = secs

h5 = tables.openFile(args.h5, mode='a',
                     filters=tables.Filters(complevel=5, complib='zlib'))
try:
    table = h5.root.data
    lasttime = table.col('time')[-1]
    ok = newdat['time'] > lasttime
    newdat = newdat[ok]
    h5.root.data.append(newdat)
except tables.NoSuchNodeError:
    table = h5.createTable(h5.root, 'data', newdat,
                           "GOES_X rates", expectedrows=2e7)
h5.root.data.flush()
h5.close()
