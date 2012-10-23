#!/usr/bin/env python

"""
Generate a timeline plot and associated JSON data for the animated version on Replan
Central.

This plot features the predicted ACIS attenuated fluence based on current ACIS orbital
fluence, 2hr average, and grating status.  It also shows DSN comms, radiation zone
passages, instrument configuration.
"""
import argparse
import glob
from itertools import izip
import json
import re
import os

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
import calc_fluence_dist as cfd
from Ska.Matplotlib import cxctime2plotdate as cxc2pd

parser = argparse.ArgumentParser(description='Get ACE data')
parser.add_argument('--data-dir',
                    default='t_pred_fluence',
                    help='Data directory')
parser.add_argument('--hours',
                    default=72.0,
                    type=float,
                    help='Hours to predict (default=72)')
parser.add_argument('--dt',
                    default=300.0,
                    type=float,
                    help='Prediction time step (secs, default=300)')
parser.add_argument('--max-slope-samples',
                    type=int,
                    help='Max number of samples when filtering by slope (default=None')
parser.add_argument('--min-flux-samples',
                    default=100,
                    type=int,
                    help='Minimum number of samples when filtering by flux (default=100)')
parser.add_argument('--test',
                    action='store_true',
                    help='Use test data')
args = parser.parse_args()

AXES_LOC = [0.05, 0.15, 0.85, 0.6]

if args.test:
    ACIS_FLUENCE_FILE = os.path.join(args.data_dir, 'current.dat')
    ACE_RATES_FILE = os.path.join(args.data_dir, 'ace.html')
    DSN_COMMS_FILE = os.path.join(args.data_dir, 'dsn_summary.yaml')
    RADMON_FILE = os.path.join(args.data_dir, 'radmon.rdb')
else:
    ACIS_FLUENCE_FILE = '/data/mta4/www/alerts/current.dat'
    ACE_RATES_FILE = '/data/mta4/www/ace.html'
    DSN_COMMS_FILE = '/proj/sot/ska/data/dsn_summary/dsn_summary.yaml'
    RADMON_FILE = '/proj/sot/ska/data/arc/iFOT_events/radmon/*.rdb'

ACE_H5_FILE = os.path.join(args.data_dir, 'ACE.h5')
HRC_H5_FILE = os.path.join(args.data_dir, 'hrc_shield.h5')


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
                         'AVERAGE (expect one)'.format(ACE_RATES_FILE, len(lines)))
    p3_avg_flux = float(lines[0].split()[4])
    return p3_avg_flux


def get_radmons():
    """
    Get Radmon events from local file that has been pulled from iFOT by
    get_iFOT_events.pl.
    """
    files = glob.glob(RADMON_FILE)
    dat = asciitable.read(sorted(files)[-1], Reader=asciitable.NoHeader,
                          names=('radmon', 'proc', 'trans', 'date', 'date2'),
                          data_start=2)
    return dat


def get_radzones(radmons):
    """
    Constuct a list of complete radiation zones from ``radmons``.
    """
    radzones = []
    for d0, d1 in zip(radmons[:-1], radmons[1:]):
        if d0['trans'] == 'Disable' and d1['trans'] == 'Enable':
            radzones.append((d0['date'], d1['date']))
    return radzones


def get_comms():
    """
    Get the list of comm passes from the DSN summary file.
    """
    dat = yaml.load(open(DSN_COMMS_FILE, 'r'))
    return dat


def zero_fluence_at_radzone(times, fluence, radzones):
    """
    For the given ``fluence`` estimate which is sampled at ``times``,
    reset the fluence to zero at the start of each of the ``radzones``.

    This works on ``fluence`` in place.
    """
    for radzone in radzones:
        t0, t1 = DateTime(radzone).secs
        ok = (times > t0) & (times <= t1)
        if np.any(ok):
            idx0 = np.flatnonzero(ok)[0]
            fluence[idx0:] -= fluence[idx0]


def calc_fluence(times, fluence0, rates, states):
    """
    For the given starting ``fluence0`` (taken from the current ACIS ops
    estimate) and predicted P3 ``rates`` and grating ``states``, return
    the integrated fluence.
    """
    for state in states:
        ok = (state['tstart'] < times) & (times < state['tstop'])
        if state['simpos'] < 40000:
            rates[ok] = 0.0
        if state['hetg'] == 'INSR':
            rates[ok] = rates[ok] / 5.0
        if state['letg'] == 'INSR':
            rates[ok] = rates[ok] / 2.0

    fluence = (fluence0 + np.cumsum(rates)) / 1e9
    return fluence


def get_ace_p3(tstart, tstop):
    """
    Get the historical ACE P3 rates and filter out bad values.
    """
    h5 = tables.openFile(ACE_H5_FILE)
    times = h5.root.data.col('time')
    p3 = h5.root.data.col('p3')
    ok = (tstart < times) & (times < tstop) & (p3 > 0)
    h5.close()
    return times[ok], p3[ok]


def get_hrc(tstart, tstop):
    """
    Get the historical HRC proxy rates and filter out bad values.
    """
    h5 = tables.openFile(HRC_H5_FILE)
    times = h5.root.data.col('time')
    hrc = h5.root.data.col('hrc_shield') * 256.0
    ok = (tstart < times) & (times < tstop) & (hrc > 0)
    h5.close()
    return times[ok], hrc[ok]


def plot_multi_line(x, y, z, bins, colors, ax):
    """
    Plot a multi-color line.
    See: http://matplotlib.sourceforge.net/examples/
               pylab_examples/multicolored_line.html
    """

    from matplotlib.collections import LineCollection
    from matplotlib.colors import ListedColormap, BoundaryNorm

    # Allow specifying bin centers, not edges
    if len(bins) == len(colors):
        bins = np.array(bins, dtype=np.float)
        bins = np.concatenate([[z.min() - 1],
                               (bins[1:] + bins[:-1]) / 2.0,
                               [z.max() + 1]])

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
    ok = (p3_times[-1] - p3_times) < 6 * 3600  # Points within 6 hrs of last available data
    x = (p3_times[ok] - p3_times[-1]) / 3600
    y = np.log10(p3_vals[ok])
    r = np.polyfit(x, y, 1)
    return r[0]


def main():
    """
    Generate the Replan Central timeline plot.
    """
    import matplotlib.patches
    import matplotlib.pyplot as plt
    from Ska.Matplotlib import plot_cxctime

    # TODO: refactor this into smaller functions where possible.

    # Basic setup.  Set times and get input states, radmons, radzones and comms.
    now = DateTime('2012:249:00:35:00' if args.test else None)
    now = DateTime(now.date[:14] + ':00')  # truncate to 0 secs
    start = now - 1.0
    stop = start + args.hours / 24.0
    states = fetch_states(start, stop,
                          server='/proj/sot/ska/data/cmd_states/cmd_states.h5')

    radmons = get_radmons()
    radzones = get_radzones(radmons)
    comms = get_comms()

    # Get the ACIS ops fluence estimate and current 2hr avg flux
    fluence_date, fluence0 = get_fluence(ACIS_FLUENCE_FILE)
    if fluence_date.secs < now.secs:
        fluence_date = now
    avg_flux = get_avg_flux(ACE_RATES_FILE)

    # Compute the predicted fluence based on the current 2hr average flux.
    fluence_times = np.arange(fluence_date.secs, stop.secs, args.dt)
    rates = np.ones_like(fluence_times) * avg_flux * args.dt
    fluence = calc_fluence(fluence_times, fluence0, rates, states)
    zero_fluence_at_radzone(fluence_times, fluence, radzones)

    # Get the realtime ACE P3 and HRC proxy values over the time range
    p3_times, p3_vals = get_ace_p3(start.secs, now.secs)
    hrc_times, hrc_vals = get_hrc(start.secs, now.secs)

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

    # Plot lines at 1.0 and 2.0 (10^9) corresponding to fluence yellow
    # and red limits.  Also plot the fluence=0 line in black.
    x0, x1 = cxc2pd([fluence_times[0], fluence_times[-1]])
    plt.plot([x0, x1], [0.0, 0.0], '-k')
    plt.plot([x0, x1], [1.0, 1.0], '--b', lw=2.0)
    plt.plot([x0, x1], [2.0, 2.0], '--r', lw=2.0)

    # Draw dummy lines off the plot for the legend
    lx = [fluence_times[0], fluence_times[-1]]
    ly = [-1, -1]
    plot_cxctime(lx, ly, '-k', lw=3, label='None', fig=fig, ax=ax)
    plot_cxctime(lx, ly, '-r', lw=3, label='HETG', fig=fig, ax=ax)
    plot_cxctime(lx, ly, '-c', lw=3, label='LETG', fig=fig, ax=ax)

    # Make a z-valued curve where the z value corresponds to the grating state.
    x = cxc2pd(fluence_times)
    y = fluence
    z = np.zeros(len(fluence_times), dtype=np.int)

    for state in states:
        ok = ((state['tstart'] < fluence_times)
              & (fluence_times <= state['tstop']))
        if state['hetg'] == 'INSR':
            z[ok] = 1
        elif state['letg'] == 'INSR':
            z[ok] = 2

    plot_multi_line(x, y, z, [0, 1, 2], ['k', 'r', 'c'], ax)

    # Plot 10, 50, 90 percentiles of fluence
    p3_fits, p3_samps, fluences = cfd.get_fluences(
        os.path.join(args.data_dir, 'ACE_hourly_avg.npy'))
    p3_slope = get_p3_slope(p3_times, p3_vals)
    hrs, fl10, fl50, fl90 = cfd.get_fluence_percentiles(
        avg_flux, p3_slope, p3_fits, p3_samps, fluences,
        args.min_flux_samples, args.max_slope_samples)
    fluence_hours = (fluence_times - fluence_times[0]) / 3600.0
    for fl_y, linecolor in zip((fl10, fl50, fl90),
                               ('-g', '-b', '-r')):
        fl_y = Ska.Numpy.interpolate(fl_y, hrs, fluence_hours)
        rates = np.diff(fl_y)
        fl_y_atten = calc_fluence(fluence_times[:-1], fluence0, rates, states)
        zero_fluence_at_radzone(fluence_times[:-1], fl_y_atten, radzones)
        plt.plot(x0 + fluence_hours[:-1] / 24.0, fl_y_atten, linecolor)

    # Set x and y axis limits
    x0, x1 = cxc2pd([start.secs, stop.secs])
    plt.xlim(x0, x1)
    y0 = -0.45
    y1 = 2.55
    plt.ylim(y0, y1)

    id_xs = []
    id_labels = []

    # Draw comm passes
    next_comm = None
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
        id_labels.append('{}:{}'.format(comm['station']['value'][4:6],
                                        comm['track_local']['value'][:9]))
        if (next_comm is None and DateTime(comm['bot_date']['value']).secs > now.secs):
            next_comm = comm

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
    id_xs.extend(cxc2pd([start.secs]))
    id_labels.append(str(states[0]['obsid']))
    for s0, s1 in zip(states[:-1], states[1:]):
        if s0['obsid'] != s1['obsid']:
            id_xs.append(cxc2pd([s1['tstart']])[0])
            id_labels.append(str(s1['obsid']))

    plt.grid()
    plt.ylabel('Attenuated fluence / 1e9')
    plt.legend(loc='upper center', labelspacing=0.15)
    lineid_plot.plot_line_ids(cxc2pd([start.secs, stop.secs]),
                              [y1, y1],
                              id_xs, id_labels, ax=ax,
                              box_axes_space=0.14,
                              label1_size=10)

    # Plot observed ACE P3 rates and limits
    lp3 = log_scale(p3_vals)
    pd = cxc2pd(p3_times)
    ox = cxc2pd([start.secs, now.secs])
    oy1 = log_scale(12000.)
    plt.plot(ox, [oy1, oy1], '--b', lw=2)
    oy1 = log_scale(55000.)
    plt.plot(ox, [oy1, oy1], '--r', lw=2)
    plt.plot(pd, lp3, '-k', alpha=0.3, lw=3)
    plt.plot(pd, lp3, '.k', mec='k', ms=3)

    # Plot observed HRC shield proxy rates and limits
    pd = cxc2pd(hrc_times)
    lhrc = log_scale(hrc_vals)
    plt.plot(pd, lhrc, '-c', alpha=0.3, lw=3)
    plt.plot(pd, lhrc, '.c', mec='c', ms=3)

    # Draw SI state
    times = np.arange(start.secs, stop.secs, 300)
    state_vals = interpolate_states(states, times)
    y_si = -0.23
    x = cxc2pd(times)
    y = np.zeros_like(times) + y_si
    z = np.zeros_like(times, dtype=np.float)  # 0 => ACIS
    z[state_vals['simpos'] < 0] = 1.0  # HRC
    plot_multi_line(x, y, z, [0, 1], ['c', 'r'], ax)
    dx = (x1 - x0) * 0.01
    plt.text(x1 + dx, y_si, 'HRC/ACIS',
             ha='left', va='center', size='small')

    # Draw log scale y-axis on left
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
    ax2.plot(lx, ly, '-k', lw=3, label='ACE')
    ax2.plot(lx, ly, '-c', lw=3, label='HRC')
    ax2.legend(loc='upper left', labelspacing=0.15)

    plt.draw()
    plt.savefig(os.path.join(args.data_dir, 'timeline.png'))

    write_states_json(os.path.join(args.data_dir, 'timeline_states.js'),
                      fig, ax, states, start, stop, now,
                      next_comm,
                      fluence, fluence_times,
                      p3_vals, p3_times,
                      hrc_vals, hrc_times)


def get_si(simpos):
    """
    Get SI corresponding to the given SIM position.
    """
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
                      next_comm,
                      fluences, fluence_times,
                      p3s, p3_times,
                      hrcs, hrc_times):
    """
    Generate JSON data file that contains all the annotation values used in the
    javascript-driven annotated plot on Replan Central.  This creates a data structure
    with state values for each 10-minute time step along the X-axis of the plot.  All of
    the hard work (formatting etc) is done here so the javascript is very simple.
    """
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
    pds = cxc2pd(times)  # Convert from CXC time to plotdate times

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
                   'pcad_mode', 'si_mode', 'power_cmd', 'letg', 'hetg')

    # Get all the state values that occur within the range of the plot
    disp_xy = data_to_disp([(pd, 0.0) for pd in pds])
    ax_xy = disp_to_ax(disp_xy)
    ok = (ax_xy[:, 0] > 0.0) & (ax_xy[:, 0] < 1.0)
    times = times[ok]
    pds = pds[ok]
    state_vals = interpolate_states(states, times)

    # Set the current values
    p3_now = p3s[-1]
    hrc_now = hrcs[-1]
    fluence_now = fluences[0]

    fluences = Ska.Numpy.interpolate(fluences, fluence_times, times)
    p3s = Ska.Numpy.interpolate(p3s, p3_times, times)
    hrcs = Ska.Numpy.interpolate(hrcs, hrc_times, times)

    # Iterate through each time step and create corresponding data structure
    # with pre-formatted values for display in the output table.
    for time, pd, state_val, fluence, p3, hrc in izip(times, pds, state_vals,
                                                      fluences, p3s, hrcs):
        out = {}
        out['date'] = date_zulu(time)
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
            out['fluence'] = '{:.2f}e9'.format(fluence_now)
            out['p3'] = '{:.0f}'.format(p3)
            out['hrc'] = '{:.0f}'.format(hrc)
        else:
            out['fluence'] = '{:.2f}e9'.format(fluence)
            out['p3'] = '{:.0f}'.format(p3_now)
            out['hrc'] = '{:.0f}'.format(hrc_now)
        outs.append(out)
    data['states'] = outs
    data['now_idx'] = now_idx
    data['now_date'] = date_zulu(now)

    track = next_comm['track_local']['value']
    data['track_time'] = ('&nbsp;&nbsp;' + track[15:19] + track[:4]
                          + ' ' + track[10:13])
    data['track_dt'] = get_fmt_dt(next_comm['bot_date']['value'], now_secs)
    data['track_station'] = '{}-{}'.format(next_comm['site']['value'],
                                           next_comm['station']['value'][4:6])
    data['track_activity'] = next_comm['activity']['value'][:14]

    # Finally write this all out as a simple javascript program that defines a single
    # variable ``data``.
    with open(fn, 'w') as f:
        f.write('var data = {}'.format(json.dumps(data)))


def date_zulu(date):
    """Format the current time in like 186/2234Z"""
    date = DateTime(date).date
    zulu = '{}/{}{}z'.format(date[5:8], date[9:11], date[12:14])
    return zulu


def get_fmt_dt(t1, t0):
    """
    Format the delta time between ``t1`` and ``t0`` in a specific way for the
    output table.
    """
    t1 = DateTime(t1).secs
    t0 = DateTime(t0).secs
    dt = t1 - t0
    adt = abs(int(round(dt)))
    days = adt // 86400
    hours = (adt - days * 86400) // 3600
    mins = int(round((adt - days * 86400 - hours * 3600) / 60))
    sign = '+' if dt >= 0 else '-'
    days = str(days) + 'd ' if days > 0 else ''
    return 'NOW {} {}{}:{:02d}'.format(sign, days, hours, mins)


def log_scale(y):
    return (np.log10(y) - 1.0) / 2.0

if __name__ == '__main__':
    main()
