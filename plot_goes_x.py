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
                    default='GOES_X_16.h5',
                    help='HDF5 file name')
args = parser.parse_args()

with tables.open_file(args.h5, mode='r') as h5:
    table = h5.root.data[:]
    # Use just last 3 days if available
    table = table[table['time'] >= (DateTime() - 3).secs ]
    h5.close()

plt.figure(1, figsize=(6, 4))
for col, wavelength, color in zip(['long', 'short'],
                                   ['0.1-0.8nm', '0.05-0.4nm'],
                                   ['red', 'blue']):
    vals = table[wave]
    vals = vals.clip(min=1e-10)
    plot_cxctime(table['time'], vals, color=color, linewidth=.5,
                 label=f'GOES 16 {wavelength}')
plt.ylim(1e-9, 1e-2)
plt.yscale('log')
plt.grid()
plt.ylabel('Watts / m**2')
plt.legend()
plt.title('GOES Xray Flux from GOES16')
plt.tight_layout()
plt.savefig(args.out)
