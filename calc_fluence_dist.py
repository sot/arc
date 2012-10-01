import numpy as np

N_FUTURE = 48
N_PAST = 6
N_T = N_FUTURE + N_PAST
N_SAMP = 6
MIN_SAMPLES = 50


def get_fluences(filename='ACE_hourly_avg.npy'):
    """
    Get P3 cumulative fluence values at 1 hour intervals for all data in the
    ACE mission since 1997, using 1-hr average P3 values.  Compute a fluence
    prediction starting each 12 hours extending for 48 hours.  Store each
    48-point fluence prediction along with the index into the global ``BINS``
    array corresponding to the starting P3 value.
    """
    dat = np.load(filename)

    # Remove bad data points
    ok = dat['p3'] > 1
    dat = dat[ok]
    p3s = dat['p3']

    # Compute data times in hours
    hrs = (dat['fp_year'] - 1997.0) * 24 * 365.25

    i0s = np.arange(0, len(p3s) - N_T, N_SAMP)
    p3_samps = np.vstack([p3s[i:i + N_T] for i in i0s])
    d_hrs = np.array([hrs[i + N_T] - hrs[i] - N_T for i in i0s])
    ok = np.abs(d_hrs) < 0.15
    p3_samps = p3_samps[ok]

    p_fits = np.polyfit(np.arange(N_PAST), np.log10(p3_samps[:, :N_PAST].T), 1)
    fluences = np.cumsum(p3_samps[:, N_PAST:], axis=1) * 3600

    return p_fits.T, p3_samps, fluences


def get_fluence_percentiles(p3_now, p3_samps, fluences):
    """
    Plot the 10%, 50%, and 90% fluence time histories within each P3 bin.
    """
    p3s = p3_samps[:, N_PAST - 1]

    bin_wid = 0.05
    while True:
        ok = np.abs(np.log10(p3s) - np.log10(p3_now)) < bin_wid
        if np.sum(ok) > MIN_SAMPLES or bin_wid > 0.5:
            break
        bin_wid *= 1.4

    p3_samps = p3_samps[ok]
    fluences = fluences[ok]
    p3s = p3s[ok]

    hrs = np.arange(1, 49)
    fluences = fluences * p3_now / p3s.reshape(-1, 1)
    fl10, fl50, fl90 = np.percentile(fluences, [10, 50, 90], axis=0)

    return hrs, fl10, fl50, fl90


if __name__ == '__main__':
    p_fits, p3_samps, fluences = get_fluences()
    print 'p3_avg_now',
    p3_avg_now = float(raw_input())
    hrs, fl10, fl50, fl90 = get_fluence_percentiles(
        p3_avg_now, p3_samps, fluences)
