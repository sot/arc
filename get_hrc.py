#!/usr/bin/env python

import argparse
import collections
import sys
import time
from pathlib import Path

import numpy as np
import requests
import tables
from astropy.table import Table
from astropy.time import Time
from Chandra.Time import DateTime

# URLs for 6 hour and 7 day JSON files
URL_NOAA = "https://services.swpc.noaa.gov/json/goes/primary/"
URL_6H = f"{URL_NOAA}/differential-protons-6-hour.json"
URL_7D = f"{URL_NOAA}/differential-protons-7-day.json"

# Bad or missing data value
BAD_VALUE = -1.0e5


def get_options():
    parser = argparse.ArgumentParser(
        description="Archive GOES data and HRC shield rate proxy"
    )
    parser.add_argument(
        "--data-dir", type=str, default=".", help="Directory for output data files"
    )
    parser.add_argument("--h5", default="hrc_shield.h5", help="HDF5 file name")
    args = parser.parse_args()
    return args


def get_json_data(url):
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
        print(f"Warning: failed to open URL {url}: {last_err}")
        sys.exit(0)

    dat = Table(data)

    return dat


def calc_hrc_shield(dat):
    # For GOES earlier than 16 use columns p5, p6, p7
    # hrc_shield = (6000 * dat['p5'] + 270000 * dat['p6']
    #               + 100000 * dat['p7']) / 256.
    # HRC proxy, GOES-16, used until April 2021
    # hrc_shield = (6000 * dat['p5'] + 270000 * dat['p7']
    #               + 100000 * dat['p9']) / 256.
    # HRC proxy model based on fitting the 2SHLDART data
    # with a combination of GOES-16 channels at the time
    # of the Sep 2017 flare
    hrc_shield = (
        143 * dat["p5"] + 64738 * dat["p6"] + 162505 * dat["p7"] + 4127
    ) / 256.0
    return hrc_shield


def format_proton_data(dat, descrs):
    """
    Manipulate the data and return them in a desired format.

    Including columns that the old h5 file format wanted.
    """

    # Create a dictionary to capture the channel data for each time
    out = collections.defaultdict(dict)
    for row in dat:
        out[row["time_tag"]][row["channel"].lower()] = row["flux"] * 1000

    # Reshape that data into a table with the channels as columns
    newdat = Table(list(out.values())).filled(BAD_VALUE)
    newdat["time_tag"] = list(out.keys())  # Already in time order if dat rows in order

    # Assume the satellite is the same for all of the records of one dat/file
    newdat["satellite"] = dat["satellite"][0]

    # Add some time columns
    times = Time(newdat["time_tag"])
    newdat["time"] = times.cxcsec
    newdat["mjd"] = times.mjd.astype(int)
    newdat["secs"] = np.array(
        np.round((times.mjd - newdat["mjd"]) * 86400, decimals=0)
    ).astype(int)
    newdat["year"] = [t.year for t in times.datetime]
    newdat["month"] = [t.month for t in times.datetime]
    newdat["dom"] = [t.day for t in times.datetime]
    newdat["hhmm"] = np.array(
        [f"{t.hour}{t.minute:02}" for t in times.datetime]
    ).astype(int)

    # Take the Table and make it into an ndarray with the supplied type
    arr = np.ndarray(len(newdat), dtype=descrs)
    for col in arr.dtype.names:
        # This gets any channels that were just missing altogether.  Looks like p2 and p11 now
        if col not in newdat.colnames:
            arr[col] = BAD_VALUE
        else:
            arr[col] = newdat[col]

    # Calculate the hrc shield values using the numpy array and save into the array
    hrc_shield = calc_hrc_shield(arr)
    arr["hrc_shield"] = hrc_shield
    hrc_bad = (arr["p5"] < 0) | (arr["p6"] < 0) | (arr["p7"] < 0)
    arr["hrc_shield"][hrc_bad] = BAD_VALUE  # flag bad inputs

    return arr, hrc_bad


def main():
    args = get_options()

    try:
        with tables.open_file(
            args.h5, mode="r", filters=tables.Filters(complevel=5, complib="zlib")
        ) as h5:
            table = h5.root.data
            descrs = table.dtype
            lasttime = table.col("time")[-1]
    except (OSError, IOError, tables.NoSuchNodeError):
        print("Warning: No previous GOES shield data, exiting")
        sys.exit(0)

    # Use the 6-hour file by default
    dat = get_json_data(url=URL_6H)
    newdat, hrc_bad = format_proton_data(dat, descrs=descrs)

    # Use the 7-day file if there is a gap
    if lasttime < newdat["time"][0]:
        print(
            "Warning: Data gap or error in GOES proton data.  Fetching 7-day JSON file"
        )
        dat = get_json_data(URL_7D)
        newdat, hrc_bad = format_proton_data(dat, descrs=descrs)

    with tables.open_file(
        args.h5, mode="a", filters=tables.Filters(complevel=5, complib="zlib")
    ) as h5:
        try:
            table = h5.root.data
            ok = newdat["time"] > lasttime
            h5.root.data.append(newdat[ok])
        except tables.NoSuchNodeError:
            table = h5.create_table(
                h5.root, "data", newdat, "HRC Antico shield + GOES", expectedrows=2e7
            )
        h5.root.data.flush()

    # Also write the mean of the last three values (15 minutes) to
    # hrc_shield.dat.  Only include good values.
    times = DateTime(newdat["time"][-3:]).unix
    hrc_shield = newdat["hrc_shield"][-3:]
    ok = ~hrc_bad[-3:]
    if len(hrc_shield[ok]) > 0:
        Path(args.data_dir).mkdir(exist_ok=True)
        with open(Path(args.data_dir, "hrc_shield.dat"), "w") as f:
            print(hrc_shield[ok].mean(), times[ok].mean(), file=f)

    # For GOES earlier than 16:
    # for colname, scale, filename in zip(
    #     ('p2', 'p5'), (3.3, 12.0), ('p4gm.dat', 'p41gm.dat')):
    # GOES-16, ``scale`` TBD
    for colname, scale, filename in zip(
        ("p4", "p7"), (3.3, 12.0), ("p4gm.dat", "p41gm.dat"), strict=False
    ):
        proxy = newdat[colname][-3:] * scale
        ok = proxy > 0
        if len(proxy[ok]) > 0:
            with open(Path(args.data_dir, filename), "w") as f:
                print(proxy[ok].mean(), times[ok].mean(), file=f)


if __name__ == "__main__":
    main()
