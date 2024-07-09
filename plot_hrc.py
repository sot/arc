#!/usr/bin/env python
import argparse

import matplotlib

matplotlib.use("agg")
import matplotlib.pyplot as plt
import tables
from Ska.Matplotlib import plot_cxctime

parser = argparse.ArgumentParser(description="Plot HRC")
parser.add_argument("--out", type=str, default="hrc_shield.png", help="Plot file name")
parser.add_argument("--h5", default="hrc_shield.h5", help="HDF5 file name")
args = parser.parse_args()

h5 = tables.open_file(args.h5, mode="r")
table = h5.root.data
secs = table.col("time")[-864:]
hrc_shield = table.col("hrc_shield")[-864:]
h5.close()

bad = hrc_shield < 0.1
hrc_shield = hrc_shield[~bad]
secs = secs[~bad]

plt.figure(1, figsize=(6, 4))
ticks, fig, ax = plot_cxctime(secs, hrc_shield)
xlims = ax.get_xlim()
dx = (xlims[1] - xlims[0]) / 20.0
ax.set_xlim(xlims[0] - dx, xlims[1] + dx)
ax.set_ylim(min(hrc_shield.min() * 0.5, 10.0), max(hrc_shield.max() * 2, 300.0))
plt.plot([xlims[0] - dx, xlims[1] + dx], [235, 235], "--r")
ax.set_yscale("log")
plt.grid()
plt.title("GOES proxy for HRC shield rate / 256")
plt.ylabel("Cts / sample")
plt.tight_layout()
plt.savefig(args.out)
