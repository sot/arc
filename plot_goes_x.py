#!/usr/bin/env python
import argparse
import matplotlib
matplotlib.use('agg')
import matplotlib.pyplot as plt
import tables
from Chandra.Time import DateTime

from Ska.Matplotlib import plot_cxctime

parser = argparse.ArgumentParser(description='')
parser.add_argument('--out', type=str,
                    default='goes_x.png',
                    help='Plot file name')
parser.add_argument('--h5',
                    default='GOES_X_16.h5',
                    help='HDF5 file name')
args = parser.parse_args()




h5 = tables.open_file(args.h5, mode='r')
table = h5.root.data[:]
# Use just last 3 days if available
table = table[table['time'] >= (DateTime() - 3).secs ]
h5.close()


plt.figure(1, figsize=(6, 4))
for wave, color in zip(['long', 'short'], ['red', 'blue']):
    vals = table[wave]
    vals[vals <= 0] = 1e-10
    ticks, fig, ax = plot_cxctime(table['time'], vals, color=color, linewidth=.5,
                                  label=f'GOES 16 {wave}')
ax.set_ylim(1e-9, 1e-2)
ax.set_yscale('log')
plt.grid()
plt.ylabel('Watts / m**2')
plt.legend()
plt.title('GOES Xray Flux from GOES16')
plt.tight_layout()
plt.savefig(args.out)
