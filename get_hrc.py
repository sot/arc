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
from astropy.time import Time

PATH = 'https://services.swpc.noaa.gov/json/goes/primary/'

def get_json_data(url=f'{PATH}/differential-protons-6-hour.json'):
    """
    Open the json file and return it as an astropy table
    """

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

    return dat


def calc_hrc_shield(dat):
    # For GOES earlier than 16 use columns p5, p6, p7
    # hrc_shield = (6000 * dat['p5'] + 270000 * dat['p6']
    #               + 100000 * dat['p7']) / 256.
    # HRC proxy, GOES-16, TBD
    hrc_shield = (6000 * dat['p5'] + 270000 * dat['p7']
                  + 100000 * dat['p9']) / 256.
    return hrc_shield


def format_proton_data(dat, descrs=None):
    """
    Manipulate the data and return them in a desired format
    including columns that the old h5 file format wanted.
    """

    if descrs is None:
        with tables.open_file('hrc_shield.h5', mode='r',
                               filters=tables.Filters(complevel=5, complib='zlib')) as h5:
            descrs = h5.root.data.dtype

    channels = [chan.lower() for chan in np.unique(dat['channel'])]

    tabs = []
    for channel in channels:
        ok = dat['channel'] == channel.upper()
        t = dat[ok]
        t.rename_column('flux', channel)
        tabs.append(t)

    newdat = np.ndarray(len(tabs[0]), dtype=descrs)

    newdat['satellite'] = tabs[0]['satellite']

    time_ref = tabs[0]['time_tag']

    for t in tabs:
        if not all(t['time_tag'] == time_ref):
            print(f'Warning: mismatch in channel time column')
            sys.exit(0)
        else:
            for col in t.colnames:
                if col in channels:
                    newdat[col] = t[col]

    # Add p11 column and the time columns the old file format wanted
    times = Time(time_ref)
    newdat['time'] = times.cxcsec
    newdat['mjd'] = times.mjd.astype(int)
    newdat['secs'] = np.array(np.round((times.mjd - newdat['mjd']) * 86400,
                                        decimals=0)).astype(int)
    newdat['year'] = [t.year for t in times.datetime]
    newdat['month'] = [t.month for t in times.datetime]
    newdat['dom'] = [t.day for t in times.datetime]
    newdat['hhmm'] = np.array([f"{t.hour}{t.minute:02}" for t in times.datetime]).astype(int)
    newdat['p11'] = np.full(len(times), -1.0e5)

    hrc_shield = calc_hrc_shield(newdat)

    newdat['hrc_shield'] = hrc_shield

    hrc_bad = (newdat['p5'] < 0) | (newdat['p7'] < 0) | (newdat['p9'] < 0)
    newdat['hrc_shield'][hrc_bad] = -1.0e5  # flag bad inputs

    return newdat, descrs, hrc_bad


def main():
    parser = argparse.ArgumentParser(description='Archive GOES data and '
                                     'HRC shield rate proxy')
    parser.add_argument('--data-dir', type=str,
                        default='.',
                        help='Directory for output data files')
    args = parser.parse_args()

    dat = get_json_data()
    newdat, descrs, hrc_bad = format_proton_data(dat)

    os.chdir(args.data_dir)

    with tables.open_file('hrc_shield.h5', mode='a',
                          filters=tables.Filters(complevel=5, complib='zlib')) as h5:
        try:
            table = h5.root.data
            lasttime = table.col('time')[-1]
            if newdat['time'][0] - lasttime > 5 * 60.0:
                # Fetch the 7-day file if a data gap is detected
                dat = get_json_data(url=f'{PATH}/differential-protons-7-day.json')
                newdat, descrs, hrc_bad = format_proton_data(dat, descrs=descrs)
            ok = newdat['time'] > lasttime
            h5.root.data.append(newdat[ok])
        except tables.NoSuchNodeError:
            table = h5.create_table(h5.root, 'data', newdat,
                                "HRC Antico shield + GOES", expectedrows=2e7)
        h5.root.data.flush()

    # Also write the mean of the last three values (15 minutes) to
    # hrc_shield.dat.  Only include good values.
    times = DateTime(newdat['time'][-3:]).unix
    hrc_shield = newdat['hrc_shield'][-3:]
    ok = ~hrc_bad[-3:]
    if len(hrc_shield[ok]) > 0:
        with open('hrc_shield.dat', 'w') as f:
            print(hrc_shield[ok].mean(), times[ok].mean(), file=f)

    # For GOES earlier than 16:
    # for colname, scale, filename in zip(
    #     ('p2', 'p5'), (3.3, 12.0), ('p4gm.dat', 'p41gm.dat')):
    # GOES-16, ``scale`` TBD
    for colname, scale, filename in zip(
        ('p4', 'p7'), (3.3, 12.0), ('p4gm.dat', 'p41gm.dat')):
        proxy = newdat[colname][-3:] * scale
        ok = proxy > 0
        if len(proxy[ok]) > 0:
            with open(filename, 'w') as f:
                print(proxy[ok].mean(), times[ok].mean(), file=f)


if __name__ == '__main__':
    main()
