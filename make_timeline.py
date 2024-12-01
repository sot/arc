#!/usr/bin/env python

"""
Generate a timeline plot and associated JSON data for animated version.

This plot features the predicted ACIS attenuated fluence based on current ACIS orbital
fluence, 2hr average, and grating status.  It also shows DSN comms, radiation zone
passages, instrument configuration.

Testing
=======
This section documents regression testing of the Replan Central timeline plot code. For
full testing of Replan Central including the ``arc.pl`` Perl script and other Python
scripts see: https://github.com/sot/arc/wiki/Set-up-test-Replan-Central.

First some setup which applies to testing both on HEAD and local::

  cd ~/git/arc
  rm -rf t_now
  COMMIT=`git rev-parse --short HEAD`
  PR=pr86  # or whatever
  mkdir -p t_now/$COMMIT
  mkdir -p t_now/flight

HEAD
-----
Testing on HEAD does an apples-to-apples comparison of the branch to the current flight
code, running both in "flight" mode::

  # Current flight version of make_timeline.py looks for data in the output directory.
  ln -s /proj/sot/ska/data/arc3/*.h5 t_now/flight/
  ln -s /proj/sot/ska/data/arc3/ACE_hourly_avg.npy t_now/flight/

  # Run PR branch version in "flight" mode (no --test), being explicit about data
  # directory. This version looks for data resources in fixed locations, not in
  # `data-dir`, so starting with an empty directory is fine.
  python make_timeline.py --data-dir=t_now/$COMMIT

  # Run flight version of make_timeline.py in a directory hidden from the git repo.
  cd t_now
  python /proj/sot/ska/share/arc3/make_timeline.py --data-dir=flight

  cd ..
  rsync -av t_now/ /proj/sot/ska/www/ASPECT_ICXC/test_review_outputs/arc/${PR}/t_now/

  diff t_now/{flight,$COMMIT}/timeline_states.js

Local
-----
Testing on a local machine (Mac) requires syncing the data files from kady.  This tests
that the branch produces the same output as the currently running flight arc cron job.

For testing on a local machine, the most straightforward option is syncing from HEAD. Do
all this in one copy/paste to reduce the chance that the cron job has run between
commands. The ``--test-get-web`` option in the last command is to grab the ACIS fluence,
ACE rates, and DSN comms from the web.

  rsync -av kady:/proj/sot/ska/data/arc3/hrc_shield.h5 $SKA/data/arc3/
  rsync -av kady:/proj/sot/ska/data/arc3/ACE.h5 $SKA/data/arc3/
  rsync -av kady:/proj/sot/ska/data/arc3/GOES_X.h5 $SKA/data/arc3/
  rsync -av kady:/proj/sot/ska/data/arc3/ACE_hourly_avg.npy $SKA/data/arc3/
  rsync -av kady:/proj/sot/ska/www/ASPECT/arc3/ t_now/$COMMIT/
  rsync -av kady:/proj/sot/ska/www/ASPECT/arc3/ t_now/flight/
  ln -s $SKA/data/arc3/ACE_hourly_avg.npy t_now/$COMMIT/
  ln -s $SKA/data/arc3/*.h5 t_now/$COMMIT/
  python make_timeline.py --data-dir=t_now/$COMMIT --test-get-web

Get the flight run date and convert that to a full date-format date (e.g. "317/1211z"
=> "2024:317:12:11:00")::

  DATE_NOW=`python utils/get_date_now.py t_now/flight`

Run the script with the test option::

  python make_timeline.py --test --data-dir=t_now/$COMMIT --date-now=$DATE_NOW

To view the output, open the directory in a browser::

  open t_now/$COMMIT/index.html
  open t_now/flight/index.html

Compare the timeline_states.js files::

  python utils/convert_states_to_yaml.py t_now/$COMMIT
  python utils/convert_states_to_yaml.py t_now/flight

  diff t_now/{flight,$COMMIT}/timeline_states.yaml
"""

import argparse
import functools
import io
import json
import os
import re
import sys
import warnings
from pathlib import Path

os.environ["MPLBACKEND"] = "Agg"

import astropy.units as u
import kadi.commands.states as kadi_states
import matplotlib.cbook
import matplotlib.patches
import matplotlib.pyplot as plt
import numpy as np
import ska_numpy
import tables
import yaml
from astropy.table import Table
from cxotime import CxoTime, CxoTimeLike
from kadi import events, occweb
from ska_matplotlib import lineid_plot, plot_cxctime

import calc_fluence_dist as cfd

warnings.filterwarnings("ignore", category=matplotlib.MatplotlibDeprecationWarning)

P3_BAD = -100000
AXES_LOC = [0.08, 0.15, 0.83, 0.6]
SKA = Path(os.environ["SKA"])
DATA_ARC3 = SKA / "data" / "arc3"
URL_AVAIL_COMMS = (
    "https://occweb.cfa.harvard.edu/mission/MissionPlanning/DSN/DSN_Modifications.csv"
)

# Define HTML to support showing available comms as a table that is hidden by default.
# The table content is inserted between the two. In a nicer world this would be in a
# Jinja template, but let's keep the footprint small.
COMMS_AVAIL_HTML_HEADER = """
<script>
    function toggleCommsAvail() {
        var x = document.getElementById("timeline-comms-available");
        var button = document.querySelector("button");
        if (x.style.display === "none") {
            x.style.display = "block";
            button.textContent = "Hide available comms";
        } else {
            x.style.display = "none";
            button.textContent = "Show available comms";
        }
    };
</script>
<br>
<div style="text-align: center;">
    <button onclick="toggleCommsAvail()">Show available comms</button>
</div>
<div id="timeline-comms-available" style="display: none; font-family: monospace;">
    <br>
    <div style="display: flex; justify-content: center;">
"""
COMMS_AVAIL_HTML_FOOTER = """
    </div>
</div>
"""


def cxc2pd(times: CxoTimeLike) -> float | np.ndarray:
    """
    Convert CXC time(s) to matplotlib plot date(s).

    This replaces the old ``ska_matplotlib.cxctime2plotdate`` function with a more
    general version that accepts any CxoTimeLike object.
    """
    return CxoTime(times).plot_date


def get_parser():
    parser = argparse.ArgumentParser(
        description="Make a timeline plot and associate table javascript"
    )
    parser.add_argument(
        "--data-dir",
        default="t_now",
        help="Data directory (default=t_now)",
    )
    parser.add_argument(
        "--hours",
        default=72.0,
        type=float,
        help="Hours to predict (default=72)",
    )
    parser.add_argument(
        "--dt",
        default=300.0,
        type=float,
        help="Prediction time step (secs, default=300)",
    )
    parser.add_argument(
        "--max-slope-samples",
        type=int,
        help="Max number of samples when filtering by slope (default=None",
    )
    parser.add_argument(
        "--min-flux-samples",
        default=100,
        type=int,
        help="Minimum number of samples when filtering by flux (default=100)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help=(
            "Use test data in data_dir (default=False). This option adjusts times in "
            "ACE, GOES, and HRC data to pretend it is up to date (if needed)."
        ),
    )
    parser.add_argument(
        "--test-scenario",
        type=int,
        help="Name of a scenario for testing missing P3 data",
    )
    parser.add_argument(
        "--test-get-web",
        action="store_true",
        help=(
            "Grab ACIS fluence, ACE rates and DSN comms from web and store in "
            "data_dir. This is a one-time operation to get the data for testing."
        ),
    )
    parser.add_argument(
        "--date-now",
        type=str,
        help="Override the current time for testing (default=now)",
    )
    return parser


def arc_data_file(
    data_dir_flight: str | Path,
    filename: str,
    data_dir_test: str | Path | None = None,
    test: bool = False,
) -> Path:
    """Get a data file path from flight data directory or test directory.

    This is intended to be used as a functools.partial function, see below.
    """
    file_dir = Path(data_dir_test) if test else Path(data_dir_flight)
    return file_dir / filename


# Define file path functions for this module
acis_fluence_file = functools.partial(
    arc_data_file, "/proj/web-cxc/htdocs/acis/Fluence", "current.dat"
)
ace_rates_file = functools.partial(arc_data_file, "/data/mta4/www", "ace.html")
dsn_comms_file = functools.partial(
    arc_data_file, SKA / "data" / "dsn_summary", "dsn_summary.yaml"
)
ace_hourly_avg_file = functools.partial(arc_data_file, DATA_ARC3, "ACE_hourly_avg.npy")
goes_x_h5_file = functools.partial(arc_data_file, DATA_ARC3, "GOES_X.h5")
ace_h5_file = functools.partial(arc_data_file, DATA_ARC3, "ACE.h5")
hrc_h5_file = functools.partial(arc_data_file, DATA_ARC3, "hrc_shield.h5")
comms_avail_file = functools.partial(arc_data_file, DATA_ARC3, "comms_avail.html")


def get_web_data(data_dir):
    """Get ACIS fluence, ACE rates, and DSN comms from CXC web pages

    Output files are placed in ``data_dir``.
    """
    import urllib.request

    urls_file_funcs = [
        ("/acis/Fluence/current.dat", acis_fluence_file),
        ("/mta/ace.html", ace_rates_file),
        ("/mta/ASPECT/dsn_summary/dsn_summary.yaml", dsn_comms_file),
    ]

    for url, file_path_func in urls_file_funcs:
        urllib.request.urlretrieve(
            "https://cxc.cfa.harvard.edu" + url, file_path_func(data_dir, test=True)
        )


def get_fluence(filename):
    """
    Get the current ACIS attenuated fluence (parse stuff below)::

      TABLE 2: ACIS FLUX AND FLUENCE BASED ON ACE DATA
      Latest valid ACIS flux and fluence data...                                   111...
      # UT Date   Time  Julian  of the  --- Electron keV ---   -------------------- Pr...
      # YR MO DA  HHMM    Day    Secs        38-53   175-315      56-78    112-187   3...
      #-------------------------------------------------------------------------------...
      2012  9  4  1915  56174   69300     5.54e+03  2.90e+01   5.92e+03   1.88e+03  4....
      ACIS Fluence data...Start DOY,SOD
      2012  9  4  1923    248   38580     1.73e+08  9.15e+05   1.39e+08   4.94e+07  1...
    """

    lines = open(filename, "r").readlines()
    vals = lines[-3].split()
    mjd = float(vals[4]) + float(vals[5]) / 86400.0
    start = CxoTime(mjd, format="mjd")
    vals = lines[-1].split()
    p3_fluence = float(vals[9])
    return start, p3_fluence


def get_comms_avail(start: CxoTime, stop: CxoTime) -> Table:
    """Get the available DSN comms from OCCweb

    Parameters
    ----------
    start : CxoTime
        Start time for the available DSN comms table
    stop : CxoTime
        Stop time for the available DSN comms table

    Returns
    -------
    dat : Table
        Table of available DSN comms
    """

    try:
        text = occweb.get_occweb_page(URL_AVAIL_COMMS)
    except Exception:
        # Do not disrupt rest of processing for this. Consider logging a warning?
        return None
    dat = Table.read(text, format="ascii", fill_values=[("NaN", "0")])

    # Deleted comms are ones that have been superseded by combined comms in this table.
    datestart = start.date
    datestop = stop.date
    ok = (
        (dat["avail_bot"] < datestop)
        & (dat["avail_eot"] > datestart)
        & (dat["type"] != "Deleted")
    )
    dat = dat[ok]

    return dat["station", "avail_bot", "avail_eot", "avail_soa", "avail_eoa"]


def get_avg_flux(
    filename,
    data_dir: str | Path | None = None,
    test: bool = False,
) -> float:
    """
    # Get the ACE 2 hour average flux (parse stuff below)

                         DE1          DE4         P2          P3        P3S..
                        38-53       175-315     47-68       115-195      11..

    AVERAGE           28126.087     147.783   32152.174   10211.739   16480..
    MINIMUM           26400.000     137.000   29400.000    9310.000   15260..
    FLUENCE          2.0251e+08  1.0640e+06  2.3150e+08  7.3525e+07  1.1866..
    """

    lines = [line for line in open(filename, "r") if line.startswith("AVERAGE   ")]
    if len(lines) != 1:
        print(
            (
                "WARNING: {} file contains {} lines that start with "
                "AVERAGE (expect one)".format(
                    ace_rates_file(data_dir, test), len(lines)
                )
            )
        )
        p3_avg_flux = P3_BAD
    else:
        p3_avg_flux = float(lines[0].split()[4])
    return p3_avg_flux


def get_radzones():
    """
    Constuct a list of complete radiation zones using kadi events
    """
    radzones = events.rad_zones.filter(start=CxoTime() - 5 * u.day, stop=None)
    return [(x.start, x.stop) for x in radzones]


def get_comms(
    data_dir: str | Path | None = None,
    test: bool = False,
) -> list:
    """
    Get the list of comm passes from the DSN summary file.
    """
    dat = yaml.safe_load(open(dsn_comms_file(data_dir, test), "r"))
    return dat


def zero_fluence_at_radzone(times, fluence, radzones):
    """
    Zero the fluence estimate at the start of each radzone.

    For the given ``fluence`` estimate which is sampled at ``times``, reset the fluence
    to zero at the start of each of the ``radzones``.

    This works on ``fluence`` in place.
    """
    for radzone in radzones:
        t0, t1 = CxoTime(radzone).secs
        ok = (times > t0) & (times <= t1)
        if np.any(ok):
            idx0 = np.flatnonzero(ok)[0]
            fluence[idx0:] -= fluence[idx0]


def calc_fluence(times, fluence0, rates, states):
    """
    Calculate the fluence based on the current fluence, rates, and grating states.

    For the given starting ``fluence0`` (taken from the current ACIS ops estimate) and
    predicted P3 ``rates`` and grating ``states``, return the integrated fluence.
    """
    for state in states:
        ok = (state["tstart"] < times) & (times < state["tstop"])
        if state["simpos"] < 40000:
            rates[ok] = 0.0
        if state["hetg"] == "INSR":
            rates[ok] = rates[ok] / 5.0
        if state["letg"] == "INSR":
            rates[ok] = rates[ok] / 2.0

    fluence = (fluence0 + np.cumsum(rates)) / 1e9
    return fluence


def get_h5_data(h5_file, col_time, col_values, start, stop, test=False):
    """
    Get data from an HDF5 file and return the time and values within the time range.
    """
    tstart = CxoTime(start).secs
    tstop = CxoTime(stop).secs

    with tables.open_file(h5_file) as h5:
        times = h5.root.data.col(col_time)
        values = h5.root.data.col(col_values)

    # If testing, it is common to have the test data file not be updated to the current
    # time. In that case, just hack the times to seem current.
    if test and (dt := tstop - times[-1]) > 3600:
        times += dt

    ok = (tstart < times) & (times <= tstop)
    return times[ok], values[ok]


def get_ace_p3(
    tstart: float,
    tstop: float,
    data_dir: str | Path | None = None,
    test: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Get the historical ACE P3 rates and filter out bad values.
    """
    times, vals = get_h5_data(
        ace_h5_file(data_dir, test), "time", "p3", tstart, tstop, test
    )
    return times, vals


def get_goes_x(
    tstart: float,
    tstop: float,
    data_dir: str | Path | None = None,
    test: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Get recent GOES 1-8 angstrom X-ray rates

    Returns
    -------
    times : np.ndarray
        Times of X-ray data
    xray_long : np.ndarray
        X-ray flux
    """
    times, vals = get_h5_data(
        goes_x_h5_file(data_dir, test), "time", "long", tstart, tstop, test
    )
    return times, vals


def get_p3_test_vals(scenario, p3_times, p3s, p3_avg, p3_fluence):
    if scenario == 1:
        # ACE unavailable for the last 8 hours.  No P3 avg from MTA.
        print("Running test scenario 1")
        p3s[:] = 100.0
        bad = p3_times[-1] - p3_times < 3600 * 8
        p3s[bad] = P3_BAD
        p3_avg = P3_BAD
        p3_fluence = 0.3e9
    elif scenario == 2:
        # ACE data flow resumes but MTA does not report an average
        # value.  Expect ACE fluence to show as red because no P3 avg
        # is available for fluence calculation.
        print("Running test scenario 2")
        p3s[:] = 5000
        dt = (p3_times[-1] - p3_times) / 3600.0
        bad = (dt < 8) & (dt > 2.5)
        p3s[bad] = P3_BAD
        p3_avg = P3_BAD
        p3_fluence = 0.3e9
    elif scenario == 3:
        # ACE data flow resumes and MTA reports an average value
        # and there is now enough data for a slope and fluence quantiles
        print("Running test scenario 3")
        p3s[:] = 5000
        dt = (p3_times[-1] - p3_times) / 3600.0
        bad = (dt < 8) & (dt > 2.5)
        p3_avg = 5000
        p3s[bad] = P3_BAD
        p3_fluence = 0.0e9
    elif scenario == 4:
        # ACE data flow resumes and MTA reports an average value,
        # but not enough data for a slope and fluence quantiles
        print("Running test scenario 4")
        p3s[:] = 5000
        dt = (p3_times[-1] - p3_times) / 3600.0
        bad = (dt < 8) & (dt > 0.5)
        p3_avg = 5000
        p3s[bad] = P3_BAD
        p3_fluence = 0.0e9
    elif scenario == 5:
        # ACE completely unavailable during period.  No P3 avg from MTA.
        print("Running test scenario 5")
        p3s[:] = P3_BAD
        p3_avg = P3_BAD
        p3_fluence = 0.3e9
    elif scenario == 6:
        # Random ACE outages
        print("Running test scenario 6")
        bad = np.random.uniform(size=len(p3s)) < 0.05
        p3s[:] = 1000.0
        p3s[bad] = P3_BAD
        p3_avg = 1000.0
        p3_fluence = 0.3e9
    return p3s, p3_avg, p3_fluence


def get_hrc(
    tstart,
    tstop,
    data_dir: str | Path | None = None,
    test: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Get the historical HRC proxy rates and filter out bad values.
    """
    times, vals = get_h5_data(
        hrc_h5_file(data_dir, test), "time", "hrc_shield", tstart, tstop, test
    )
    return times, vals * 256.0


def plot_multi_line(x, y, z, bins, colors, ax):
    """
    Plot a multi-color line.

    See:
    http://matplotlib.sourceforge.net/examples/pylab_examples/multicolored_line.html
    """

    from matplotlib.collections import LineCollection
    from matplotlib.colors import BoundaryNorm, ListedColormap

    # If there are the same number of bins as colors, infer that the
    # bins are supplied as bin centers, and calculate the edges.
    if len(bins) == len(colors):
        bins = np.array(bins, dtype=float)
        centers = (bins[1:] + bins[:-1]) / 2.0
        bins = np.concatenate([[centers[0] - 1], centers, [centers[-1] + 1]])

    cmap = ListedColormap(colors)
    norm = BoundaryNorm(bins, cmap.N)

    points = np.array([x, y]).T.reshape(-1, 1, 2)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)

    lc = LineCollection(segments, cmap=cmap, norm=norm)
    lc.set_array(z)
    lc.set_linewidth(3)
    ax.add_collection(lc)


def get_p3_slope(p3_times, p3_vals):
    """
    Compute the slope (log10(p3) per hour) of the last 6 hours of ACE P3 values.
    """
    ok = (
        p3_times[-1] - p3_times
    ) < 6 * 3600  # Points within 6 hrs of last available data
    ok = ok & (p3_vals > 0)  # Good P3 values
    slope = None
    if np.sum(ok) > 4:
        x = (p3_times[ok] - p3_times[-1]) / 3600
        if x[-1] - x[0] > 2:
            y = np.log10(p3_vals[ok])
            slope = np.polyfit(x, y, 1)[0]

    return slope


def main(args_sys=None):
    """
    Generate the Replan Central timeline plot.
    """
    parser = get_parser()
    args = parser.parse_args(args_sys)

    if args.test_get_web:
        get_web_data(args.data_dir)
        sys.exit(0)

    # Basic setup.  Set times and get input states, radzones and comms.
    now = CxoTime(args.date_now)
    now = CxoTime(now.date[:14] + ":00")  # truncate to 0 secs
    start = now - 1.0 * u.day
    stop = start + args.hours * u.hour
    states = kadi_states.get_states(start=start, stop=stop)
    radzones = get_radzones()
    comms = get_comms()

    # Get the ACIS ops fluence estimate and current 2hr avg flux
    fluence_date, fluence0 = get_fluence(
        acis_fluence_file(args.data_dir, test=args.test)
    )
    fluence_date = max(fluence_date, now)
    avg_flux = get_avg_flux(ace_rates_file(args.data_dir, test=args.test))

    # Get the realtime ACE P3 and HRC proxy values over the time range
    goes_x_times, goes_x_vals = get_goes_x(start, now, args.data_dir, args.test)
    p3_times, p3_vals = get_ace_p3(start, now, args.data_dir, args.test)
    hrc_times, hrc_vals = get_hrc(start, now, args.data_dir, args.test)

    # For testing: inject predefined values for different scenarios
    if args.test_scenario:
        p3_vals, avg_flux, fluence0 = get_p3_test_vals(
            args.test_scenario, p3_times, p3_vals, avg_flux, fluence0
        )

    # Compute the predicted fluence based on the current 2hr average flux.
    fluence_times = np.arange(fluence_date.secs, stop.secs, args.dt)
    rates = np.ones_like(fluence_times) * max(avg_flux, 0.0) * args.dt
    fluence = calc_fluence(fluence_times, fluence0, rates, states)
    zero_fluence_at_radzone(fluence_times, fluence, radzones)
    comms_avail = get_comms_avail(now, stop)

    # Initialize the main plot figure
    fig = plt.figure(1, figsize=(9, 5))
    fig.patch.set_alpha(0.0)
    ax = fig.add_axes(AXES_LOC, facecolor="w")
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    ax.yaxis.set_offset_position("right")
    ax.patch.set_alpha(1.0)

    draw_ace_yellow_red_limits(fluence_times, ax)
    draw_dummy_lines_letg_hetg_legend(fluence_times, fig, ax)
    draw_fluence_and_grating_state_line(states, fluence_times, fluence, ax)
    draw_fluence_percentiles(
        args, states, radzones, fluence0, avg_flux, p3_times, p3_vals, fluence_times, ax
    )
    x0, x1, y0, y1 = set_plot_x_y_axis_limits(start, stop, ax)
    id_xs, id_labels, next_comm = draw_communication_passes(
        now, comms, ax, x0, x1, y0, y1
    )
    draw_radiation_zones(start, stop, radzones, ax, y0, y1)
    draw_now_line(now, y0, y1, id_xs, id_labels, ax)
    add_labels_for_obsids(start, states, id_xs, id_labels)

    ax.grid()
    ax.set_ylabel("Attenuated fluence / 1e9")
    ax.legend(loc="upper center", labelspacing=0.15, fontsize=10)
    # NOTE: this function call must be BEFORE any functions that add ax.text() labels to
    # the plot. For some reason if there are ax.text() labels you get an exception:
    #     box.xyann = (wlp[i], box.xyann[1])
    #                          ^^^^^^^^^
    # AttributeError: 'Text' object has no attribute 'xyann'
    lineid_plot.plot_line_ids(
        cxc2pd([start.secs, stop.secs]),
        [y1, y1],
        id_xs,
        id_labels,
        ax=ax,
        box_axes_space=0.14,
        label1_size=10,
    )

    draw_comms_avail(comms_avail, ax, x0, x1)
    draw_goes_x_data(goes_x_times, goes_x_vals, ax)
    draw_ace_p3_and_limits(now, start, p3_times, p3_vals, ax)
    draw_hrc_proxy(hrc_times, hrc_vals, ax)
    draw_hrc_acis_states(start, stop, states, ax, x0, x1)

    # Draw log scale y-axis on left
    draw_log_scale_axes(fig, y0, y1)

    fig.savefig(os.path.join(args.data_dir, "timeline.png"))

    write_states_json(
        os.path.join(args.data_dir, "timeline_states.js"),
        fig,
        ax,
        states,
        start,
        stop,
        now,
        next_comm,
        fluence,
        fluence_times,
        p3_vals,
        p3_times,
        avg_flux,
        hrc_vals,
        hrc_times,
    )
    write_comms_avail(comms_avail, comms_avail_file(args.data_dir, test=args.test))


def draw_log_scale_axes(fig, y0, y1):
    ax2 = fig.add_axes(AXES_LOC, facecolor="w", frameon=False)
    ax2.set_autoscale_on(False)
    ax2.xaxis.set_visible(False)
    ax2.set_xlim(0, 1)
    ax2.set_yscale("log")
    ax2.set_ylim(np.power(10.0, np.array([y0, y1]) * 2 + 1))
    ax2.set_ylabel("ACE flux / HRC proxy / GOES X-ray")
    ax2.text(-0.015, 2.5e3, "M", ha="right", color="m", weight="demibold")
    ax2.text(-0.015, 2.5e4, "X", ha="right", color="m", weight="semibold")

    # Draw dummy lines off the plot for the legend
    lx = [0, 1]
    ly = [1, 1]
    ax2.plot(lx, ly, "-k", lw=3, label="ACE")
    ax2.plot(lx, ly, "-c", lw=3, label="HRC")
    ax2.plot(lx, ly, "-m", lw=3, label="GOES-X")
    ax2.legend(loc="upper left", labelspacing=0.15, fontsize=10)


def draw_hrc_acis_states(start, stop, states, ax, x0, x1):
    times = np.arange(start.secs, stop.secs, 300)
    state_vals = kadi_states.interpolate_states(states, times)
    y_si = -0.23
    x = cxc2pd(times)
    y = np.zeros_like(times) + y_si
    z = np.zeros_like(times, dtype=float)  # 0 => ACIS
    z[state_vals["simpos"] < 0] = 1.0  # HRC
    plot_multi_line(x, y, z, [0, 1], ["c", "r"], ax)
    dx = (x1 - x0) * 0.01
    ax.text(x1 + dx, y_si, "HRC/ACIS", ha="left", va="center", size="small")


def draw_comms_avail(comms_avail: Table, ax, x0, x1):
    """Draw available comms as a gray strip below the ACE/HRC multi-line plot"""
    y_comm0 = -0.38
    dy_comm = 0.05
    dx = (x1 - x0) * 0.01

    # Draw comm passes
    for comm in comms_avail:
        pd0, pd1 = cxc2pd([comm["avail_bot"], comm["avail_eot"]])
        patch = matplotlib.patches.Rectangle(
            (pd0, y_comm0),
            pd1 - pd0,
            dy_comm,
            alpha=0.5,
            facecolor="k",
            edgecolor="none",
        )
        ax.add_patch(patch)
    ax.text(x1 + dx, y_comm0, "Avail comms", ha="left", va="center", size="small")


def draw_hrc_proxy(hrc_times, hrc_vals, ax):
    pd = cxc2pd(hrc_times)
    lhrc = log_scale(hrc_vals)
    ax.plot(pd, lhrc, "-c", alpha=0.3, lw=3)
    ax.plot(pd, lhrc, ".c", mec="c", ms=3)


def draw_ace_p3_and_limits(now, start, p3_times, p3_vals, ax):
    lp3 = log_scale(p3_vals)
    pd = cxc2pd(p3_times)
    ox = cxc2pd([start.secs, now.secs])
    oy1 = log_scale(12000.0)
    ax.plot(ox, [oy1, oy1], "--b", lw=2)
    oy1 = log_scale(55000.0)
    ax.plot(ox, [oy1, oy1], "--r", lw=2)
    ax.plot(pd, lp3, "-k", alpha=0.3, lw=3)
    ax.plot(pd, lp3, ".k", mec="k", ms=3)


def draw_goes_x_data(goes_x_times, goes_x_vals, ax):
    pd = cxc2pd(goes_x_times)
    lgoesx = log_scale(goes_x_vals * 1e8)
    ax.plot(pd, lgoesx, "-m", alpha=0.3, lw=1.5)
    ax.plot(pd, lgoesx, ".m", mec="m", ms=3)


def add_labels_for_obsids(start, states, id_xs, id_labels):
    id_xs.extend(cxc2pd([start.secs]))
    id_labels.append(str(states[0]["obsid"]))
    for s0, s1 in zip(states[:-1], states[1:], strict=False):
        if s0["obsid"] != s1["obsid"]:
            id_xs.append(cxc2pd([s1["tstart"]])[0])
            id_labels.append(str(s1["obsid"]))


def draw_now_line(now, y0, y1, id_xs, id_labels, ax):
    ax.plot([now.plot_date, now.plot_date], [y0, y1], "-g", lw=4)
    id_xs.extend(cxc2pd([now.secs]))
    id_labels.append("NOW")


def draw_radiation_zones(start, stop, radzones, ax, y0, y1):
    for rad0, rad1 in radzones:
        t0 = CxoTime(rad0)
        t1 = CxoTime(rad1)
        if t0 < stop and t1 > start:
            t0 = max(t0, start)
            t1 = min(t1, stop)
            pd0, pd1 = t0.plot_date, t1.plot_date
            p = matplotlib.patches.Rectangle(
                (pd0, y0),
                pd1 - pd0,
                y1 - y0,
                alpha=0.2,
                facecolor="b",
                edgecolor="none",
            )
            ax.add_patch(p)


def draw_communication_passes(now, comms, ax, x0, x1, y0, y1):
    id_xs = []
    id_labels = []

    # Draw comm passes
    next_comm = None
    for comm in comms:
        pd0, pd1 = cxc2pd([comm["bot_date"]["value"], comm["eot_date"]["value"]])
        if pd1 >= x0 and pd0 <= x1:
            p = matplotlib.patches.Rectangle(
                (pd0, y0),
                pd1 - pd0,
                y1 - y0,
                alpha=0.2,
                facecolor="r",
                edgecolor="none",
            )
            ax.add_patch(p)
        id_xs.append((pd0 + pd1) / 2)
        id_labels.append(
            "{}:{}".format(
                comm["station"]["value"][4:6], comm["track_local"]["value"][:9]
            )
        )
        if next_comm is None and CxoTime(comm["bot_date"]["value"]) > now:
            next_comm = comm
    return id_xs, id_labels, next_comm


def draw_fluence_percentiles(
    args, states, radzones, fluence0, avg_flux, p3_times, p3_vals, fluence_times, ax
):
    """Plot 10, 50, 90 percentiles of fluence"""
    try:
        if len(p3_times) < 4:
            raise ValueError("not enough P3 values")
        p3_slope = get_p3_slope(p3_times, p3_vals)
        if p3_slope is not None and avg_flux > 0:
            p3_fits, p3_samps, fluences = cfd.get_fluences(
                ace_hourly_avg_file(args.data_dir, test=args.test),
            )
            hrs, fl10, fl50, fl90 = cfd.get_fluence_percentiles(
                avg_flux,
                p3_slope,
                p3_fits,
                p3_samps,
                fluences,
                args.min_flux_samples,
                args.max_slope_samples,
            )
            fluence_hours = (fluence_times - fluence_times[0]) / 3600.0
            for fl_y, linecolor in zip(
                (fl10, fl50, fl90), ("-g", "-b", "-r"), strict=False
            ):
                fl_y = ska_numpy.interpolate(fl_y, hrs, fluence_hours)  # noqa: PLW2901
                rates = np.diff(fl_y)
                fl_y_atten = calc_fluence(fluence_times[:-1], fluence0, rates, states)
                zero_fluence_at_radzone(fluence_times[:-1], fl_y_atten, radzones)
                ax.plot(
                    cxc2pd(fluence_times[0]) + fluence_hours[:-1] / 24.0,
                    fl_y_atten,
                    linecolor,
                )
    except Exception as e:
        print(("WARNING: p3 fluence not plotted, error : {}".format(e)))


def set_plot_x_y_axis_limits(start, stop, ax):
    x0, x1 = start.plot_date, stop.plot_date
    ax.set_xlim(x0, x1)
    y0 = -0.45
    y1 = 2.55
    ax.set_ylim(y0, y1)
    return x0, x1, y0, y1


def draw_fluence_and_grating_state_line(states, fluence_times, fluence, ax):
    """Make a z-valued curve where the z value corresponds to the grating state."""

    x = cxc2pd(fluence_times)
    y = fluence
    z = np.zeros(len(fluence_times), dtype=int)

    for state in states:
        ok = (state["tstart"] < fluence_times) & (fluence_times <= state["tstop"])
        if state["hetg"] == "INSR":
            z[ok] = 1
        elif state["letg"] == "INSR":
            z[ok] = 2

    plot_multi_line(x, y, z, [0, 1, 2], ["k", "r", "c"], ax)


def draw_dummy_lines_letg_hetg_legend(fluence_times, fig, ax):
    lx = [fluence_times[0], fluence_times[-1]]
    ly = [-1, -1]
    plot_cxctime(lx, ly, "-k", lw=3, label="None", fig=fig, ax=ax)
    plot_cxctime(lx, ly, "-r", lw=3, label="HETG", fig=fig, ax=ax)
    plot_cxctime(lx, ly, "-c", lw=3, label="LETG", fig=fig, ax=ax)


def draw_ace_yellow_red_limits(fluence_times, ax):
    # Plot lines at 1.0 and 2.0 (10^9) corresponding to fluence yellow
    # and red limits.  Also plot the fluence=0 line in black.
    x0, x1 = cxc2pd([fluence_times[0], fluence_times[-1]])
    ax.plot([x0, x1], [0.0, 0.0], "-k")  # ?? I don't see this line
    ax.plot([x0, x1], [1.0, 1.0], "--b", lw=2.0)
    ax.plot([x0, x1], [2.0, 2.0], "--r", lw=2.0)


def get_si(simpos):
    """
    Get SI corresponding to the given SIM position.
    """
    if (simpos >= 82109) and (simpos <= 104839):
        si = "ACIS-I"
    elif (simpos >= 70736) and (simpos <= 82108):
        si = "ACIS-S"
    elif (simpos >= -86147) and (simpos <= -20000):
        si = " HRC-I"
    elif (simpos >= -104362) and (simpos <= -86148):
        si = " HRC-S"
    else:
        si = "  NONE"
    return si


def date_to_zulu(date):
    """
    Convert a date string to a Zulu time string.
    """
    return CxoTime(date).date[9:14].replace(":", "")


def write_comms_avail(comms_avail: Table, filename: str | Path):
    """Make a simple HTML table of the available communication passes.

    Support (GMT)   BOT  EOT  Station   Site       Track time (local)
    --------------- ---- ---- --------- ---------  -------------------------
    318/1345-1600   1445 1545 DSS-24    GOLDSTONE  0945-1045 EST, Wed 13 Nov
    318/2115-0000   2215 2345 DSS-26    GOLDSTONE  1715-1845 EST, Wed 13 Nov
    319/1100-1315   1200 1300 DSS-54    MADRID     0700-0800 EST, Thu 14 Nov
    """
    rows = []
    for comm in comms_avail:
        soa = CxoTime(comm["avail_soa"])
        eoa = CxoTime(comm["avail_eoa"])
        bot = CxoTime(comm["avail_bot"])
        eot = CxoTime(comm["avail_eot"])

        support_doy = soa.date[5:8]
        support_startz = date_to_zulu(soa)
        support_endz = date_to_zulu(eoa)
        support_gmt = f"{support_doy}/{support_startz}-{support_endz}"

        station = comm["station"]
        station_num = int(station[-2:])
        if station_num < 30:
            site = "GOLDSTONE"
        elif station_num < 50:
            site = "CANBERRA"
        else:
            site = "MADRID"

        # local time looks like '2024 Sun Nov 17 04:58:09 AM EST'
        pattern = (
            r"(?P<year>\d{4}) (?P<day_name>\w{3}) (?P<month>\w{3}) "
            r"(?P<day>\d{2}) (?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2}) "
            r"(?P<period>AM|PM) (?P<tz>\w{3})"
        )
        match = re.match(pattern, bot.get_conversions()["local"])
        bot_local = match.groupdict()
        track_bot = (
            f"{bot_local['day_name']} {bot_local['month']} {bot_local['day']} "
            f"{bot_local['hour']}:{bot_local['minute']} "
            f"{bot_local['period']} {bot_local['tz']}"
        )

        dur = eot - bot
        dur_secs = np.round(dur.sec)
        dur_hr = int(dur_secs // 3600)
        dur_min = int((dur_secs - dur_hr * 3600) // 60)
        dur_hr_min = f"{dur_hr}:{dur_min:02d}"

        row = (
            support_gmt,
            date_to_zulu(comm["avail_bot"]),
            date_to_zulu(comm["avail_eot"]),
            station,
            site,
            track_bot,
            dur_hr_min,
        )
        rows.append(row)

    comms_avail = Table(
        rows=rows,
        names=(
            "Support (GMT)",
            "BOT",
            "EOT",
            "Station",
            "Site",
            "Track time (local)",
            "Dur",
        ),
    )

    out = io.StringIO()
    comms_avail.write(out, format="ascii.html")
    # Get the text between <table> and </table> and write out.
    match = re.search("<table>(.*)</table>", out.getvalue(), re.DOTALL)
    Path(filename).write_text(
        COMMS_AVAIL_HTML_HEADER + match.group(0) + COMMS_AVAIL_HTML_FOOTER
    )


def write_states_json(
    filename,
    fig,
    ax,
    states,
    start,
    stop,
    now,
    next_comm,
    fluences,
    fluence_times,
    p3s,
    p3_times,
    p3_avg,
    hrcs,
    hrc_times,
):
    """
    Write JSON states.

    Generate JSON data file that contains all the annotation values used in the
    javascript-driven annotated plot on Replan Central.  This creates a data structure
    with state values for each 10-minute time step along the X-axis of the plot.  All of
    the hard work (formatting etc) is done here so the javascript is very simple.
    """
    formats = {
        "ra": "{:10.4f}",
        "dec": "{:10.4f}",
        "roll": "{:10.4f}",
        "pitch": "{:8.2f}",
        "obsid": "{:5d}",
    }
    start = start - 1 * u.day
    tstop = (stop + 1 * u.day).secs
    tstart = CxoTime(start.date[:8] + ":00:00:00").secs
    times = np.arange(tstart, tstop, 600)
    pds = cxc2pd(times)  # Convert from CXC time to plotdate times

    # Set up matplotlib transforms
    data_to_disp = ax.transData.transform
    ax_to_disp = ax.transAxes.transform
    disp_to_ax = ax.transAxes.inverted().transform
    disp_to_fig = fig.transFigure.inverted().transform

    disp_xy = ax_to_disp([(0, 0), (1, 1)])
    fig_xy = disp_to_fig(disp_xy)
    data = {"ax_x": fig_xy[:, 0].tolist(), "ax_y": fig_xy[:, 1].tolist()}

    outs = []
    now_idx = 0
    now_secs = now.secs
    state_names = (
        "obsid",
        "simpos",
        "pitch",
        "ra",
        "dec",
        "roll",
        "pcad_mode",
        "si_mode",
        "power_cmd",
        "letg",
        "hetg",
    )

    # Get all the state values that occur within the range of the plot
    disp_xy = data_to_disp([(pd, 0.0) for pd in pds])
    ax_xy = disp_to_ax(disp_xy)
    ok = (ax_xy[:, 0] > 0.0) & (ax_xy[:, 0] < 1.0)
    times = times[ok]
    pds = pds[ok]
    state_vals = kadi_states.interpolate_states(states, times)

    # Set the current values
    p3_now = p3s[-1]
    hrc_now = hrcs[-1]
    fluence_now = fluences[0]

    fluences = ska_numpy.interpolate(fluences, fluence_times, times)
    p3s = ska_numpy.interpolate(p3s, p3_times, times)
    hrcs = ska_numpy.interpolate(hrcs, hrc_times, times)

    # Iterate through each time step and create corresponding data structure
    # with pre-formatted values for display in the output table.
    NOT_AVAIL = "N/A"
    for time, pd, state_val, fluence, p3, hrc in zip(  # noqa: B007
        times, pds, state_vals, fluences, p3s, hrcs, strict=False
    ):
        out = {}
        out["date"] = date_zulu(time)
        for name in state_names:
            val = state_val[name].tolist()
            fval = formats.get(name, "{}").format(val)
            out[name] = re.sub(" ", "&nbsp;", fval)
        out["ccd_fep"] = "{}, {}".format(state_val["ccd_count"], state_val["fep_count"])
        out["vid_clock"] = "{}, {}".format(
            state_val["vid_board"], state_val["clocking"]
        )
        out["si"] = get_si(state_val["simpos"])
        out["now_dt"] = get_fmt_dt(time, now_secs)
        if time < now_secs:
            now_idx += 1
            out["fluence"] = "{:.2f}e9".format(fluence_now)
            out["p3"] = "{:.0f}".format(p3) if p3 > 0 else NOT_AVAIL
            out["hrc"] = "{:.0f}".format(hrc)
        else:
            out["fluence"] = "{:.2f}e9".format(fluence)
            out["p3"] = "{:.0f}".format(p3_now) if p3_now > 0 else NOT_AVAIL
            out["hrc"] = "{:.0f}".format(hrc_now)
        outs.append(out)
    data["states"] = outs
    data["now_idx"] = now_idx
    data["now_date"] = date_zulu(now)
    data["p3_avg_now"] = "{:.0f}".format(p3_avg) if p3_avg > 0 else NOT_AVAIL
    data["p3_now"] = "{:.0f}".format(p3_now) if p3_now > 0 else NOT_AVAIL
    data["hrc_now"] = "{:.0f}".format(hrc_now)

    track = next_comm["track_local"]["value"]
    data["track_time"] = "&nbsp;&nbsp;" + track[15:19] + track[:4] + " " + track[10:13]
    data["track_dt"] = get_fmt_dt(next_comm["bot_date"]["value"], now_secs)
    data["track_station"] = "{}-{}".format(
        next_comm["site"]["value"], next_comm["station"]["value"][4:6]
    )
    data["track_activity"] = next_comm["activity"]["value"][:14]

    # Finally write this all out as a simple javascript program that defines a single
    # variable ``data``.
    with open(filename, "w") as f:
        f.write("var data = {}".format(json.dumps(data)))


def date_zulu(date):
    """Format the current time in like 186/2234Z"""
    date = CxoTime(date).date
    zulu = "{}/{}{}z".format(date[5:8], date[9:11], date[12:14])
    return zulu


def get_fmt_dt(t1, t0):
    """
    Format delta time between ``t1`` and ``t0`` for the output table.
    """
    t1 = CxoTime(t1).secs
    t0 = CxoTime(t0).secs
    dt = t1 - t0
    adt = abs(int(round(dt)))
    days = adt // 86400
    hours = (adt - days * 86400) // 3600
    mins = int(round((adt - days * 86400 - hours * 3600) / 60))
    sign = "+" if dt >= 0 else "-"
    days = str(days) + "d " if days > 0 else ""
    return "NOW {} {}{}:{:02d}".format(sign, days, hours, mins)


def log_scale(y):
    if isinstance(y, np.ndarray):
        bad = y <= 0
        y = y.copy()
        y[bad] = 1e-10
    return (np.log10(y) - 1.0) / 2.0


if __name__ == "__main__":
    main()
