#!/usr/bin/env python
# Licensed under a 3-clause BSD style license - see LICENSE.rst
"""
Plot GOES X-ray data for use in Replan Central
"""

import argparse
import matplotlib
matplotlib.use('agg')
import matplotlib.pyplot as plt
import tables

from Chandra.Time import DateTime
from Ska.Matplotlib import plot_cxctime

parser = argparse.ArgumentParser(description='Plot GOES X data for Replan Central')
parser.add_argument('--out', type=str,
                    default='goes_x.png',
                    help='Plot file name')
parser.add_argument('--h5',
                    default='GOES_X.h5',
                    help='HDF5 file name')
args = parser.parse_args()

with tables.open_file(args.h5, mode='r') as h5:
    table = h5.root.data[:]
    # Use just last 3 days if available
    table = table[table['time'] >= (DateTime() - 3).secs ]
    h5.close()

fig = plt.figure(1, figsize=(6, 4))
ax1 = fig.add_subplot(1, 1, 1)
for col, wavelength, color in zip(['long', 'short'],
                                   ['0.1-0.8nm', '0.05-0.4nm'],
                                   ['red', 'blue']):

    vals = table[col]
    vals = vals.clip(min=1e-10)
    plot_cxctime(table['time'], vals, color=color, linewidth=.5,
                 label=f'{wavelength}', ax=ax1)

ax1.set_ylim(1e-9, 1e-2)
ax1.set_yscale('log')
ax1.set_ylabel('Watts / m**2')
ax1.grid()
ax1.legend()
ax2 = ax1.twinx()
ax2.set_yscale('log')
ax2.set_ylim(1e-9, 1e-2)
plt.tight_layout()
plt.subplots_adjust(right=0.91)
plt.text(1.06, .7, 'Xray Flare Class',
         transform=ax1.transAxes, rotation=270)
ticks = [4e-8, 4e-7, 4e-6, 4e-5, 4e-4]
labels = ['A', 'B', 'C', 'M', 'X']
ax2.set_yticks(ticks)
ax2.set_yticklabels(labels)
ax2.tick_params(length=0)
plt.title('GOES Xray Flux')
plt.savefig(args.out)
