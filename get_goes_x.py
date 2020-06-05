#!/usr/bin/env python
# Licensed under a 3-clause BSD style license - see LICENSE.rst
"""
Fetch GOES X-ray data and update h5 table

The code now works from SWPC JSON files from GOES 16.  The GOES 15
data was updated to include a column for 'satellite' with this gist:

https://gist.github.com/jeanconn/2a34a5219129ed090f8bfaee5582788d

"""

import sys
import urllib.request
import urllib.error
import urllib.parse
import argparse
import tables
import time
import json

import numpy as np
from astropy.table import Table, join
from astropy.time import Time

# URLs for 6 hour and 7 day JSON files
URL_6H = 'https://services.swpc.noaa.gov/json/goes/primary/xrays-6-hour.json'
URL_7D = 'https://services.swpc.noaa.gov/json/goes/primary/xrays-7-day.json'


def get_options():
    parser = argparse.ArgumentParser(description='Get GOES_X data')
    parser.add_argument('--h5',
                        default='GOES_X.h5',
                        help='HDF5 file name')
    parser.add_argument('--satellite',
                        type=int,
                        help='Select which satelite from the json file by int id')
    args = parser.parse_args()
    return args


def get_json_data(url):
    """
    Fetch SWPC data file at url and return as astropy table
    """
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
        print(('Malformed GOES_X data from SWPC; Table(json.loads(urldat)) did not succeed: {}'
               .format(err)))
        sys.exit(0)
    return dat


def process_xray_data(dat, satellite=None):
    """
    Take the astropy table of 'dat' and rearrange to give a single
    row for each sample time, include the historical time
    columns, and add a column to describe the satellite.

    If optional satellite arg is supplied, filter the source data to include
    only records that match that satellite.
    """

    if len(dat) == 0:
        print('Warning: No data in fetched file')
        sys.exit(0)

    # Select only the GOES satellite specified from the args
    if satellite is not None:
        dat = dat[dat['satellite'] == satellite]
        if len(dat) == 0:
            print('Warning: No data in fetched file for satellite {}'.format(satellite))
            sys.exit(0)

    # Make a table for each of the two wavelengths
    shortdat = dat[dat['energy'] == '0.05-0.4nm']['flux', 'satellite', 'time_tag']
    shortdat.rename_column('flux', 'short')
    longdat = dat[dat['energy'] == '0.1-0.8nm']['flux', 'satellite', 'time_tag']
    longdat.rename_column('flux', 'long')
    if len(longdat) != len(shortdat):
        print('Warning: "short" and "long" table have mismatched lengths')

    # Join them on time and satellite (seems to be OK for these data)
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
    joindat['hhmm'] = np.array([
        f"{t.hour}{t.minute:02}" for t in times.datetime]).astype(int)

    joindat['ratio'] = -100000.0
    ok = (joindat['long'] != 0) & (joindat['long'] != -100000.0)
    joindat['ratio'][ok] = joindat['short'][ok] / joindat['long'][ok]

    return joindat['year', 'month', 'dom', 'hhmm', 'mjd', 'secs',
                   'short', 'long', 'ratio', 'time', 'satellite'].as_array()


def main():

    args = get_options()

    # Read the data file just to get the last record
    try:
        with tables.open_file(args.h5, mode='r',
                              filters=tables.Filters(complevel=5, complib='zlib')) as h5:
            table = h5.root.data
            lasttime = table.col('time')[-1]
    except (OSError, IOError, tables.NoSuchNodeError):
        print("Warning: No previous GOES X data, using -1 as last time")
        lasttime = -1

    # Use the 6 hour file by default
    dat = get_json_data(URL_6H)
    newdat = process_xray_data(dat, args.satellite)

    # Use the 7-day file if there is a gap
    if lasttime < newdat['time'][0]:
        print("Warning: Data gap or error in X-ray data.  Fetching 7-day JSON file")
        dat = get_json_data(URL_7D)
        newdat = process_xray_data(dat, args.satellite)

    # Print a warning if there is still a gap
    if lasttime < newdat['time'][0]:
        print(
            f"Warning: Gap from {lasttime} to X-ray 7-day start {newdat['time'][0]}")

    # Update the data table with the new records
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


if __name__ == '__main__':
    main()

