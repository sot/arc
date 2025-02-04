import argparse
from pathlib import Path
import shutil
from ska_helpers.web_utils import get_last_referenced_web_image


URL = "https://www.solen.info/solar/index.html"
IMAGE_SRC_PATTERN = r'(images/AR_CH_\d{8}.png)'

def get_options():
    parser = argparse.ArgumentParser(description="Get solar flare png")
    parser.add_argument("--image-cache-dir", default="./last_solar_flare_image",
                        help="Directory for image cache")
    parser.add_argument("--out-file", default="solar_flare.png",
                        help="Output file name")
    return parser


def main(sys_args=None):
    args = get_options().parse_args(sys_args)

    img = get_last_referenced_web_image(
        url=URL,
        img_src_pattern=IMAGE_SRC_PATTERN,
        cache_dir=Path(args.image_cache_dir))

    # Copy the image to the standard name
    standard_image_path = Path(args.out_file)
    shutil.copy(img, standard_image_path)


if __name__ == "__main__":
    main()

