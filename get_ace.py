#!/usr/bin/env python

import sys
import urllib2
import argparse
import tables
import time

import numpy as np
import asciitable
from Chandra.Time import DateTime

parser = argparse.ArgumentParser(description='Get ACE data')
parser.add_argument('--h5',
                    default='ACE.h5',
                    help='HDF5 file name')
args = parser.parse_args()

url = 'http://www.swpc.noaa.gov/ftpdir/lists/ace/ace_epam_5m.txt'

colnames = ('year month dom  hhmm  mjd secs p1  p2  p3 '
            'p4  p5  p6  p7  p8  p9 p10 p11').split()

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

colnames = ('year month dom  hhmm  mjd secs '
            'destat de1 de4 pstat p1 p3 p5 p6 p7 anis_idx').split()

try:
    dat = asciitable.read(urldat, guess=False, Reader=asciitable.NoHeader,
                          data_start=3, header_start=3, names=colnames)
except Exception as err:
    print('Warning: malformed ACE data so table read failed: {}'
          .format(err))
    sys.exit(0)

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
    print 'Adding {} records to {} at {}'.format(len(newdat), args.h5,
                                                 time.ctime())
except tables.NoSuchNodeError:
    table = h5.createTable(h5.root, 'data', newdat,
                           "ACE rates", expectedrows=2e7)
h5.root.data.flush()
h5.close()
