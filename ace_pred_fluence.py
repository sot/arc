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
    names = ('year', 'mon', 'day', 'hhmm',  'doy', 'de1', 'de4', 'p2', 'p3')
    vals = lines[-1].split()[:len(names)]
    f0 = dict(zip(names, vals))
    f0['doy'] = '{:03d}'.format(int(f0['doy']))

    start = '{}:{}:{:02d}:{:02d}:00'.format(
        f0['year'], f0['doy'],
        int(f0['hhmm'][-4:-2] or '0'), int(f0['hhmm'][-2:]))
    start = DateTime(start)
    p3_fluence = float(f0['p3'])
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


def get_comms():
    dat = yaml.load(open(DSN_COMMS_FILE, 'r'))
    return dat


def zero_fluence_at_radmon(times, fluence, radmons):
    for radmon in radmons:
        t_trans = DateTime(radmon['date']).secs
        if (radmon['trans'] == 'Disable' and
            t_trans > times[0] and t_trans < times[-1]):
            i_trans = np.searchsorted(times, t_trans)
            fluence[i_trans:] -= fluence[i_trans]


def calc_fluence(start, stop, dt):
    dt = args.dt
    times = np.arange(start.secs, stop.secs, dt)
    rates = np.ones_like(times) * p3_avg_flux * dt
    for state in states:
        ok = (state['tstart'] < times) & (times < state['tstop'])
        if state['simpos'] < 40000:
            rates[ok] = 0.0
        if state['hetg'] == 'INSR':
            rates[ok] = rates[ok] / 5.0
        if state['letg'] == 'INSR':
            rates[ok] = rates[ok] / 2.0

    fluence = (p3_fluence0 + np.cumsum(rates)) / 1e9
    return times, fluence


def make_plot(times, fluence, states, radmons, comms):
    """
    See: http://matplotlib.sourceforge.net/examples/pylab_examples/multicolored_line.html
    """
    import matplotlib.patches
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from matplotlib.colors import ListedColormap, BoundaryNorm
    from Ska.Matplotlib import plot_cxctime, cxctime2plotdate

    plt.clf()
    plot_cxctime([times[0], times[-1]], [-1, -1], '-r', lw=3, label='None')
    plot_cxctime([times[0], times[-1]], [-1, -1], '-b', lw=3, label='LETG')
    plot_cxctime([times[0], times[-1]], [-1, -1], '-g', lw=3, label='HETG')

    x = cxctime2plotdate(times)
    y = fluence
    z = np.zeros(len(times), dtype=np.int)

    for state in states:
        ok = (state['tstart'] < times) & (times <= state['tstop'])
        if np.any(ok):
            if state['hetg'] == 'INSR':
                z[ok] = 1
            elif state['letg'] == 'INSR':
                z[ok] = 2

    cmap = ListedColormap(['r', 'g', 'b'])
    norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5], cmap.N)

    points = np.array([x, y]).T.reshape(-1, 1, 2)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)

    lc = LineCollection(segments, cmap=cmap, norm=norm)
    lc.set_array(z)
    lc.set_linewidth(3)
    ax = plt.gca()
    ax.add_collection(lc)

    x0, x1 = plt.xlim()
    plt.plot([x0, x1], [1.0, 1.0], '--g', lw=2.0)
    plt.plot([x0, x1], [2.0, 2.0], '--r', lw=2.0)
    y0 = -0.1
    y1 = max(2.05, np.max(fluence) * 1.05)
    plt.ylim(y0, y1)

    for comm in comms:
        tstart = DateTime(comm['bot_date']['value']).secs
        tstop = DateTime(comm['eot_date']['value']).secs
        pd_start, pd_stop = cxctime2plotdate([tstart, tstop])
        if pd_stop >= x0 and pd_start <= x1:
            p = matplotlib.patches.Rectangle((pd_start, 0.0),
                                             pd_stop - pd_start,
                                             y1 - y0,
                                             alpha=0.2,
                                             facecolor='r',
                                             edgecolor='none')
            ax.add_patch(p)

    plt.draw()
    plt.grid()
    plt.ylabel('Attenuated fluence / 1e9')
    plt.legend(loc='upper left')

radmons = get_radmons()
comms = get_comms()

start, p3_fluence0 = get_fluence(ACIS_FLUENCE_FILE)
p3_avg_flux = get_avg_flux(ACE_RATES_FILE)
stop = start + args.hours / 24.0
if args.test:
    states = asciitable.read(CMD_STATES_FILE)
else:
    states = fetch_states(start, stop, vals=['obsid', 'simpos', 'hetg', 'letg'])

times, fluence = calc_fluence(start, stop, args.dt)
zero_fluence_at_radmon(times, fluence, radmons)

make_plot(times, fluence, states, radmons, comms)
