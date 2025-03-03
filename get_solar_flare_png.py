#!/usr/bin/env python
# Licensed under a 3-clause BSD style license - see LICENSE.rst
import argparse
import re
import shutil
from pathlib import Path
from urllib.parse import urljoin

import requests
from ska_helpers import retry

URL = "https://www.solen.info/solar/index.html"
IMAGE_SRC_PATTERN = r"<img src=\"(images/AR_CH_\d{8}\.png)\""


def get_options():
    parser = argparse.ArgumentParser(description="Get solar flare png")
    parser.add_argument(
        "--image-cache-dir",
        required=True,
        help="Directory for image cache",
    )
    parser.add_argument("--out-file", required=True, help="Output file name")
    return parser


@retry.retry(exceptions=requests.exceptions.RequestException, delay=5, tries=3)
def get_last_referenced_web_image(
    url: str, img_src_pattern: str, cache_dir: str | Path
) -> Path:
    """
    Get the image from a web page matching a pattern and download it.

    This caches the files to avoid downloading files we already have.
    This works for the case when the image referenced in the HTML has a file name
    that is changed when the file is updated.

    Parameters
    ----------
    url : str
        The URL of the web page to get the image from.
    img_src_pattern : str
        The regular expression pattern to match the image source.
    cache_dir : str or Path
        The directory to cache the image in. If not supplied, a default
        directory will be used in the user's home directory.

    Returns
    -------
    cached_image_file : Path
        The path to the cached image.
    """

    # Make cache directory
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Fetch the web page and get the html
    response = requests.get(url)
    # Check that the request was successful
    response.raise_for_status()
    html = response.text

    # get absolute url of the image that matches the supplied pattern
    pattern = re.compile(img_src_pattern)
    match = pattern.search(html)
    if match:
        img_src = match.group(1)
        img_url = urljoin(url, img_src)
    else:
        raise ValueError("No image found matching the pattern")

    # What is the file name of the image?
    img_filename = Path(img_url).name

    # If the image is already in the cache, return it
    cached_image_file = cache_dir / img_filename
    if cached_image_file.exists():
        return cached_image_file

    # Delete any files in the cache directory
    for file in cache_dir.iterdir():
        file.unlink()

    # Download the new image and save it to the cache directory
    response = requests.get(img_url)
    # Check that the request was successful
    response.raise_for_status()

    with open(cached_image_file, "wb") as f:
        f.write(response.content)

    # And return the cached image path
    return cached_image_file


def main(sys_args=None):
    args = get_options().parse_args(sys_args)

    img_file = get_last_referenced_web_image(
        url=URL, img_src_pattern=IMAGE_SRC_PATTERN, cache_dir=Path(args.image_cache_dir)
    )

    # Copy the image to the standard name
    standard_image_path = Path(args.out_file)
    shutil.copy(img_file, standard_image_path)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        traceback.print_exc()
