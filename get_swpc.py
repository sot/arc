#!/usr/bin/env python
import os
import requests
import argparse
import time

parser = argparse.ArgumentParser(description='Get SWPC web data')
parser.add_argument('--out', default='.', help="output directory for fetched files")
args = parser.parse_args()

swpc_urls = {'sgarf.txt': 'https://services.swpc.noaa.gov/text/sgarf.txt',
             'GOES_xray.gif': 'https://services.swpc.noaa.gov/images/goes-xray-flux.gif',
             'ACE_5min.gif': 'http://services.swpc.noaa.gov/images/ace-epam-7-day.gif'}

for locname, url in swpc_urls.items():
    for _ in range(3):
        try:
            outfile = os.path.join(args.out, locname)
            response = requests.get(url)
            with open(outfile, 'wb') as fh:
                fh.write(response.content)
            break
        except Exception as err:
            time.sleep(5)
    else:
        print 'Warning: failed to open URL {}: {}'.format(url, err)

