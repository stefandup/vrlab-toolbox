import os
from datetime import datetime

import click
import pyxdf
from rich import print

from vrlab_toolbox.config import get_default_xdf


def check_mobi_xdf(xdf_fn=None, verbose=False):

    if not xdf_fn:
        xdf_fn = get_default_xdf()

    # expected_streams = config.getlist("expected_streams","required")
    # expected_stream_nr = len(expected_streams)

    print(f"Loading xdf at {os.path.basename(xdf_fn)}...")

    streams, header = pyxdf.load_xdf(xdf_fn)
    dt = datetime.fromisoformat(header["info"]["datetime"][0])
    print(f"Stream started at {dt.strftime('%A, %d %B %Y at %H:%M:%S %Z')}")
    # print(f"Recoded {len(streams)} out of {expected_stream_nr} streams")

    # TODO: Show missing streams

    # Print information about the streams
    if verbose:
        print("-" * 40)

        for stream in streams:
            print(f"Stream Name: {stream['info']['name'][0]}")
            print(f"Stream Type: {stream['info']['type'][0]}")
            print(f"Stream created at {stream['info']['created_at'][0]}")
            # print(pd.to_datetime(stream['info']['created_at'][0], unit="s", origin="unix"))
            print(f"Number of Channels: {stream['info']['channel_count'][0]}")
            print(f"Channel Format: {stream['info']['channel_format'][0]}")
            print(f"Sampling Rate: {stream['info']['nominal_srate'][0]}")
            print(f"Number of Samples: {len(stream['time_series'])}")
            # print("Sample Time Series Data:", stream[ 'time_series'][:5])
            # print("Sample Time Stamps:", stream['time_stamps'][:5])
            print("Dictionary Keys:", stream.keys())

        print("-" * 40)

    return streams


@click.command()
@click.version_option(package_name="mooi-toolbox")
@click.argument("xdf_fn", type=click.Path(exists=True, dir_okay=True), required=False)
@click.option("--verbose", is_flag=True, help="Give verbose output")
def main(xdf_fn, verbose):

    return check_mobi_xdf(xdf_fn=xdf_fn, verbose=verbose)


if __name__ == "__main__":
    main()
