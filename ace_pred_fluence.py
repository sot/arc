#!/usr/bin/env python

"""
Predict ACIS attenuated fluence based on current ACIS orbital fluence, 2hr
average, and grating status.
"""
import argparse
import glob

import numpy as np
import yaml

import asciitable
from Chandra.Time import DateTime
from Chandra.cmd_states import fetch_states
import lineid_plot

parser = argparse.ArgumentParser(description='Get ACE data')
parser.add_argument('--hours',
                    default=96.0,
                    type=float,
                    help='Hours to predict (default=36)')
parser.add_argument('--dt',
                    default=300.0,
                    type=float,
                    help='Prediction time step (secs, default=300)')
parser.add_argument('--test',
                    action='store_true',
                    help='Use test data')
args = parser.parse_args()

if args.test:
    ACIS_FLUENCE_FILE = 't_pred_fluence/current.dat'
    ACE_RATES_FILE = 't_pred_fluence/ace.html'
    DSN_COMMS_FILE = 't_pred_fluence/dsn_summary.yaml'
    RADMON_FILE = 't_pred_fluence/radmon.rdb'
    CMD_STATES_FILE = 't_pred_fluence/states.dat'
    ACE_H5_FILE = 't_pred/ACE.h5'
    HRC_H5_FILE = 't_pred/hrc_shield.h5'
else:
    ACIS_FLUENCE_FILE = '/data/mta4/www/alerts/current.dat'
    ACE_RATES_FILE = '/data/mta4/www/ace.html'
    DSN_COMMS_FILE = '/proj/sot/ska/data/dsn_summary/dsn_summary.yaml'
    RADMON_FILE = '/proj/sot/ska/data/arc/iFOT_events/radmon/*.rdb'


def get_fluence(filename):
    """
    Get the current ACIS attenuated fluence (parse stuff below)
    TABLE 2: ACIS FLUX AND FLUENCE BASED ON ACE DATA

    Latest valid ACIS flux and fluence data...                                   111...
    # UT Date   Time  Julian  of the  --- Electron keV ---   -------------------- Pr...
    # YR MO DA  HHMM    Day    Secs        38-53   175-315      56-78    112-187   3...
    #-------------------------------------------------------------------------------...
    2012  9  4  1915  56174   69300     5.54e+03  2.90e+01   5.92e+03   1.88e+03  4....
    ACIS Fluence data...Start DOY,SOD
    2012  9  4  1923    248   38580     1.73e+08  9.15e+05   1.39e+08   4.94e+07  1...
    """

    lines = open(filename, 'r').readlines()
    vals = lines[-3].split()
    mjd = float(vals[4]) + float(vals[5]) / 86400.0
    start = DateTime(mjd, format='mjd')
    vals = lines[-1].split()
    p3_fluence = float(vals[9])
    return start, p3_fluence


def get_avg_flux(filename):
    """
    # Get the ACE 2 hour average flux (parse stuff below)

                         DE1          DE4         P2          P3        P3S..
                        38-53       175-315     47-68       115-195      11..

    AVERAGE           28126.087     147.783   32152.174   10211.739   16480..
    MINIMUM           26400.000     137.000   29400.000    9310.000   15260..
    FLUENCE          2.0251e+08  1.0640e+06  2.3150e+08  7.3525e+07  1.1866..
    """

    lines = [line for line in open(filename, 'r')
             if line.startswith('AVERAGE   ')]
    if len(lines) != 1:
        raise ValueError('{} file contains {} lines that start with '
                         'AVERAGE (expect one)'.format(
                ACE_RATES_FILE, len(lines)))
    p3_avg_flux = float(lines[0].split()[4])
    return p3_avg_flux


def get_radmons():
    files = glob.glob(RADMON_FILE)
    dat = asciitable.read(sorted(files)[-1], Reader=asciitable.NoHeader,
                          names=('radmon', 'proc', 'trans', 'date', 'date2'),
                          data_start=2)
    return dat


def get_radzones(radmons):
    radzones = []
    for d0, d1 in zip(radmons[:-1], radmons[1:]):
        if d0['trans'] == 'Disable' and d1['trans'] == 'Enable':
            radzones.append((d0['date'], d1['date']))
    return radzones


def get_comms():
    dat = yaml.load(open(DSN_COMMS_FILE, 'r'))
    return dat


def zero_fluence_at_radzone(times, fluence, radzones):
    for radzone in radzones:
        t0, t1 = DateTime(radzone).secs
        ok = (times > t0) & (times <= t1)
        if np.any(ok):
            idx0 = np.flatnonzero(ok)[0]
            fluence[idx0:] -= fluence[idx0]


def calc_fluence(start, stop, dt, fluence0, avg_flux, states):
    dt = args.dt
    times = np.arange(start.secs, stop.secs, dt)
    rates = np.ones_like(times) * avg_flux * dt
    for state in states:
        ok = (state['tstart'] < times) & (times < state['tstop'])
        if state['simpos'] < 40000:
            rates[ok] = 0.0
        if state['hetg'] == 'INSR':
            rates[ok] = rates[ok] / 5.0
        if state['letg'] == 'INSR':
            rates[ok] = rates[ok] / 2.0

    fluence = (fluence0 + np.cumsum(rates)) / 1e9
    return times, fluence


def main():
    """
    """
    import matplotlib.patches
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from matplotlib.colors import ListedColormap, BoundaryNorm
    from Ska.Matplotlib import plot_cxctime
    from Ska.Matplotlib import cxctime2plotdate as cxc2pd

    now = DateTime('2012:249:00:35:00' if args.test else None)
    # now = DateTime('2012:251:00:35:00' if args.test else None)
    start = now - 1.0
    stop = start + args.hours / 24.0

    # if args.test:
    #     states = asciitable.read(CMD_STATES_FILE)
    #     states['tstart'][:] = DateTime(states['datestart']).secs
    #     states['tstop'][:] = DateTime(states['datestop']).secs
    # else:
    states = fetch_states(start, stop,
                          vals=['obsid', 'simpos', 'hetg', 'letg'])

    radmons = get_radmons()
    radzones = get_radzones(radmons)
    comms = get_comms()

    fluence_date, fluence0 = get_fluence(ACIS_FLUENCE_FILE)
    if fluence_date.secs < now.secs:
        fluence_date = now
    avg_flux = get_avg_flux(ACE_RATES_FILE)

    fluence_times, fluence = calc_fluence(fluence_date, stop, args.dt,
                                          fluence0, avg_flux, states)
    zero_fluence_at_radzone(fluence_times, fluence, radzones)

    # Initialize the main plot figure
    plt.rc('legend', fontsize=10)
    fig = plt.figure(1, figsize=(8, 5))
    fig.clf()
    ax = fig.add_axes([0.1, 0.15, 0.85, 0.6], axis_bgcolor='w')
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position('right')

    # Draw dummy lines off the plot for the legend
    lx = [fluence_times[0], fluence_times[-1]]
    ly = [-1, -1]
    plot_cxctime(lx, ly, '-k', lw=3, label='None', fig=fig, ax=ax)
    plot_cxctime(lx, ly, '-g', lw=3, label='HETG', fig=fig, ax=ax)
    plot_cxctime(lx, ly, '-b', lw=3, label='LETG', fig=fig, ax=ax)

    # Make a z-valued curve where the z value corresponds to the
    # grating state.
    x = cxc2pd(fluence_times)
    y = fluence
    z = np.zeros(len(fluence_times), dtype=np.int)

    for state in states:
        ok = ((state['tstart'] < fluence_times)
              & (fluence_times <= state['tstop']))
        if np.any(ok):
            if state['hetg'] == 'INSR':
                z[ok] = 1
            elif state['letg'] == 'INSR':
                z[ok] = 2

    # See: http://matplotlib.sourceforge.net/examples/
    #            pylab_examples/multicolored_line.html
    cmap = ListedColormap(['k', 'b', 'g'])
    norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5], cmap.N)

    points = np.array([x, y]).T.reshape(-1, 1, 2)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)

    lc = LineCollection(segments, cmap=cmap, norm=norm)
    lc.set_array(z)
    lc.set_linewidth(3)
    ax.add_collection(lc)

    # Plot lines at 1.0 and 2.0 (10^9) corresponding to fluence yellow
    # and red limits.
    x0, x1 = cxc2pd([fluence_times[0], fluence_times[-1]])
    plt.plot([x0, x1], [1.0, 1.0], '--g', lw=2.0)
    plt.plot([x0, x1], [2.0, 2.0], '--r', lw=2.0)

    # Set x and y axis limits
    x0, x1 = cxc2pd([start.secs, stop.secs])
    plt.xlim(x0, x1)
    y0 = -0.1
    y1 = max(2.05, np.max(fluence) * 1.05)
    plt.ylim(y0, y1)

    id_xs = []
    id_labels = []

    # Draw comm passes
    for comm in comms:
        t0 = DateTime(comm['bot_date']['value']).secs
        t1 = DateTime(comm['eot_date']['value']).secs
        pd0, pd1 = cxc2pd([t0, t1])
        if pd1 >= x0 and pd0 <= x1:
            p = matplotlib.patches.Rectangle((pd0, y0),
                                             pd1 - pd0,
                                             y1 - y0,
                                             alpha=0.2,
                                             facecolor='r',
                                             edgecolor='none')
            ax.add_patch(p)
        id_xs.append((pd0 + pd1) / 2)
        id_labels.append(comm['track_local']['value'][:9])

    # Draw radiation zones
    radzones = get_radzones(radmons)
    for rad0, rad1 in radzones:
        t0 = DateTime(rad0).secs
        t1 = DateTime(rad1).secs
        if t0 < stop.secs and t1 > start.secs:
            if t0 < start.secs:
                t0 = start.secs
            if t1 > stop.secs:
                t1 = stop.secs
            pd0, pd1 = cxc2pd([t0, t1])
            p = matplotlib.patches.Rectangle((pd0, y0),
                                             pd1 - pd0,
                                             y1 - y0,
                                             alpha=0.2,
                                             facecolor='b',
                                             edgecolor='none')
            ax.add_patch(p)

    # Draw now line
    plt.plot(cxc2pd([now.secs, now.secs]), [y0, y1], '-g', lw=4)
    id_xs.extend(cxc2pd([now.secs]))
    id_labels.append('NOW')

    # Add labels for obsids
    for s0, s1 in zip(states[:-1], states[1:]):
        if s0['obsid'] != s1['obsid']:
            id_xs.append(cxc2pd([s1['tstart']])[0])
            id_labels.append('Obs {}'.format(s1['obsid']))

    plt.draw()
    plt.grid()
    plt.ylabel('Attenuated fluence / 1e9')
    plt.legend(loc='upper left')
    lineid_plot.plot_line_ids(cxc2pd([start.secs, stop.secs]),
                              [0.0, 0.0],
                              id_xs, id_labels, ax=ax,
                              box_axes_space=0.14,
                              label1_size=10)


if __name__ == '__main__':
    main()
