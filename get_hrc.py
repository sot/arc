#!/usr/bin/env python

import sys
import re
import urllib2
import argparse
import tables
import time

import numpy as np
import asciitable
from Chandra.Time import DateTime

parser = argparse.ArgumentParser(description='Archive GOES data and '
                                 'HRC shield rate proxy')
parser.add_argument('--file', type=str,
                    default='Gp_pchan_5m.txt',
                    help='GOES file name')
parser.add_argument('--h5',
                    default='Gp_pchan_5m.h5',
                    help='HDF5 file name')
args = parser.parse_args()

url = 'http://www.swpc.noaa.gov/ftpdir/lists/pchan/' + args.file
colnames = ('year month dom  hhmm  mjd secs p1  p2  p3 '
            'p4  p5  p6  p7  p8  p9 p10 p11').split()
try:
    urlob = urllib2.urlopen(url)
    urldat = urlob.read()
except:
    print 'Warning: failed to open URL'
    sys.exit(0)

dat = asciitable.read(urldat, Reader=asciitable.NoHeader, names=colnames,
                      header_start=3, data_start=3)
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
newdat['time'] = secs

h5 = tables.openFile(args.h5, mode='a',
                     filters=tables.Filters(complevel=5, complib='zlib'))
try:
    table = h5.root.data
    lasttime = table.col('time')[-1]
    ok = newdat['time'] > lasttime
    newdat = newdat[ok]
    h5.root.data.append(newdat)
    print 'Adding {} records to {} at {}'.format(len(newdat), args.h5,
                                                 time.ctime())
except tables.NoSuchNodeError:
    table = h5.createTable(h5.root, 'data', newdat,
                           "HRC Antico shield + GOES", expectedrows=2e7)
h5.root.data.flush()
h5.close()

# Also write the last value to <args.h5 prefix>.dat
filename = re.sub(r'\.[^.]*$', '', args.h5) + '.dat'
with open(filename, 'w') as f:
    print >>f, hrc_shield.mean()
