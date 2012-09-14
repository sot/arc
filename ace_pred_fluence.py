#!/usr/bin/env python

"""
Predict ACIS attenuated fluence based on current ACIS orbital fluence, 2hr
average, and grating status.
"""
import argparse
import glob
from itertools import izip
import json
import re

import numpy as np
import yaml
import tables

import matplotlib
matplotlib.use('Agg')

import Ska.Numpy
import asciitable
from Chandra.Time import DateTime
from Chandra.cmd_states import fetch_states, interpolate_states
import lineid_plot
from Ska.Matplotlib import cxctime2plotdate as cxc2pd

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

AXES_LOC = [0.05, 0.15, 0.85, 0.6]

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

ACE_H5_FILE = '/proj/sot/ska/data/arc/ACE.h5'
HRC_H5_FILE = '/proj/sot/ska/data/arc/hrc_shield.h5'


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


def get_ace_p3(tstart, tstop):
    h5 = tables.openFile(ACE_H5_FILE)
    times = h5.root.data.col('time')
    p3 = h5.root.data.col('p3')
    ok = (tstart < times) & (times < tstop) & (p3 > 0)
    h5.close()
    return times[ok], p3[ok]


def get_hrc(tstart, tstop):
    h5 = tables.openFile(HRC_H5_FILE)
    times = h5.root.data.col('time')
    hrc = h5.root.data.col('hrc_shield') * 256.0
    ok = (tstart < times) & (times < tstop) & (hrc > 0)
    h5.close()
    return times[ok], hrc[ok]


def main():
    """
    """
    import matplotlib.patches
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from matplotlib.colors import ListedColormap, BoundaryNorm
    from Ska.Matplotlib import plot_cxctime

    now = DateTime('2012:249:00:35:00' if args.test else None)
    start = now - 1.0
    stop = start + args.hours / 24.0
    if args.test:
        states = asciitable.read(CMD_STATES_FILE)
        states['tstart'][:] = DateTime(states['datestart']).secs
        states['tstop'][:] = DateTime(states['datestop']).secs
    else:
        states = fetch_states(start, stop)

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
    fig = plt.figure(1, figsize=(9, 5))
    fig.clf()
    fig.patch.set_alpha(0.0)
    ax = fig.add_axes(AXES_LOC, axis_bgcolor='w')
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position('right')
    ax.yaxis.set_offset_position('right')
    ax.patch.set_alpha(1.0)

    # Draw dummy lines off the plot for the legend
    lx = [fluence_times[0], fluence_times[-1]]
    ly = [-1, -1]
    plot_cxctime(lx, ly, '-k', lw=3, label='None', fig=fig, ax=ax)
    plot_cxctime(lx, ly, '-r', lw=3, label='HETG', fig=fig, ax=ax)
    plot_cxctime(lx, ly, '-c', lw=3, label='LETG', fig=fig, ax=ax)

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
    cmap = ListedColormap(['k', 'c', 'r'])
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
            id_labels.append('{}'.format(s1['obsid']))

    plt.grid()
    plt.ylabel('Attenuated fluence / 1e9')
    plt.legend(loc='upper center', labelspacing=0.15)
    lineid_plot.plot_line_ids(cxc2pd([start.secs, stop.secs]),
                              [y1, y1],
                              id_xs, id_labels, ax=ax,
                              box_axes_space=0.14,
                              label1_size=10)

    # Plot observed ACE P3 rates and limits
    p3_times, p3 = get_ace_p3(start.secs, now.secs)
    lp3 = log_scale(p3)
    pd = cxc2pd(p3_times)
    ox = cxc2pd([start.secs, now.secs])
    oy1 = log_scale(12000.)
    plt.plot(ox, [oy1, oy1], '--k', lw=2)
    oy1 = log_scale(55000.)
    plt.plot(ox, [oy1, oy1], '--k', lw=2)
    plt.plot(pd, lp3, '-r', alpha=0.3, lw=3)
    plt.plot(pd, lp3, '.r', mec='r', ms=3)

    # Plot observed HRC shield proxy rates and limits
    hrc_times, hrc = get_hrc(start.secs, now.secs)
    pd = cxc2pd(hrc_times)
    lhrc = log_scale(hrc)
    plt.plot(pd, lhrc, '-b', alpha=0.3, lw=3)
    plt.plot(pd, lhrc, '.b', mec='b', ms=3)

    ax2 = fig.add_axes(AXES_LOC, axis_bgcolor='w',
                       frameon=False)
    ax2.set_autoscale_on(False)
    ax2.xaxis.set_visible(False)
    ax2.set_xlim(0, 1)
    ax2.set_yscale('log')
    ax2.set_ylim(np.power(10.0, np.array([y0, y1]) * 2 + 1))

    # Draw dummy lines off the plot for the legend
    lx = [0, 1]
    ly = [1, 1]
    ax2.plot(lx, ly, '-r', lw=3, label='ACE')
    ax2.plot(lx, ly, '-b', lw=3, label='HRC')
    ax2.legend(loc='upper left', labelspacing=0.15)

    plt.draw()
    plt.savefig('ace_pred_fluence.png')

    write_states_json('timeline_states.js', fig, ax, states, start, stop, now,
                      fluence, fluence_times,
                      p3, p3_times,
                      hrc, hrc_times)


def get_si(simpos):
    if ((simpos >= 82109) and (simpos <= 104839)):
        si = 'ACIS-I'
    elif ((simpos >= 70736) and (simpos <= 82108)):
        si = 'ACIS-S'
    elif ((simpos >= -86147) and (simpos <= -20000)):
        si = ' HRC-I'
    elif ((simpos >= -104362) and (simpos <= -86148)):
        si = ' HRC-S'
    else:
        si = '  NONE'
    return si


def write_states_json(fn, fig, ax, states, start, stop, now,
                      fluences, fluence_times,
                      p3s, p3_times,
                      hrcs, hrc_times):
    formats = {'ra': '{:10.4f}',
               'dec': '{:10.4f}',
               'roll': '{:10.4f}',
               'pitch': '{:8.2f}',
               'obsid': '{:5d}',
               }
    start = start - 1
    tstop = (stop + 1).secs
    tstart = DateTime(start.date[:8] + ':00:00:00').secs
    times = np.arange(tstart, tstop, 600)
    pds = cxc2pd(times)

    # Set up matplotlib transforms
    data_to_disp = ax.transData.transform
    ax_to_disp = ax.transAxes.transform
    disp_to_ax = ax.transAxes.inverted().transform
    disp_to_fig = fig.transFigure.inverted().transform

    disp_xy = ax_to_disp([(0, 0), (1, 1)])
    fig_xy = disp_to_fig(disp_xy)
    data = {'ax_x': fig_xy[:, 0].tolist(),
            'ax_y': fig_xy[:, 1].tolist()}

    outs = []
    now_idx = 0
    now_secs = now.secs
    state_names = ('obsid', 'simpos', 'pitch', 'ra', 'dec', 'roll',
                   'pcad_mode', 'si_mode', 'power_cmd')
    disp_xy = data_to_disp([(pd, 0.0) for pd in pds])
    ax_xy = disp_to_ax(disp_xy)
    ok = (ax_xy[:, 0] > 0.0) & (ax_xy[:, 0] < 1.0)
    times = times[ok]
    pds = pds[ok]
    state_vals = interpolate_states(states, times)

    fluences = Ska.Numpy.interpolate(fluences, fluence_times, times)
    p3s = Ska.Numpy.interpolate(p3s, p3_times, times)
    hrcs = Ska.Numpy.interpolate(hrcs, hrc_times, times)

    for time, pd, state_val, fluence, p3, hrc in izip(times, pds, state_vals,
                                                      fluences, p3s, hrcs):
        out = {}
        out['date'] = DateTime(time).date[5:14]
        for name in state_names:
            val = state_val[name].tolist()
            fval = formats.get(name, '{}').format(val)
            out[name] = re.sub(' ', '&nbsp;', fval)
        out['ccd_fep'] = '{}, {}'.format(state_val['ccd_count'],
                                         state_val['fep_count'])
        out['vid_clock'] = '{}, {}'.format(state_val['vid_board'],
                                           state_val['clocking'])
        out['si'] = get_si(state_val['simpos'])
        out['now_dt'] = get_fmt_dt(time, now_secs)
        if time < now_secs:
            now_idx += 1
            out['fluence'] = ''
            out['p3'] = '{:.0f}'.format(p3)
            out['hrc'] = '{:.0f}'.format(hrc)
        else:
            out['fluence'] = '{:.2f} 10^9'.format(fluence)
            out['p3'] = ''
            out['hrc'] = ''
        outs.append(out)
    data['states'] = outs
    data['now_idx'] = now_idx

    with open(fn, 'w') as f:
        f.write('var data = {}'.format(json.dumps(data)))


def get_fmt_dt(t1, t0):
    dt = t1 - t0
    adt = abs(int(dt))
    days = adt // 86400
    hours = (adt - days * 86400) // 3600
    mins = (adt - days * 86400 - hours * 3600) // 60
    sign = '+' if dt >= 0 else '-'
    days = str(days) + 'd ' if days > 0 else ''
    return '{}{}{}:{:02d}'.format(sign, days, hours, mins)


def log_scale(y):
    return (np.log10(y) - 1.0) / 2.0

if __name__ == '__main__':
    main()
