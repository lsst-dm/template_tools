
import argparse

from common import get_endpoints, get_bad_visit_lists
from pathlib import Path


from astropy.time import Time
from astropy.table import Table



if __name__ == '__main__':

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", "-o", type=Path, default="bad_visits.ecsv",
        help="Output ecsv file",
    )

    args = parser.parse_args()

    endpoints = get_endpoints()

    day_obs_min = '2025-04-24'
    day_obs_max = Time.now().iso.split()[0]
    bad_visit_ids = get_bad_visit_lists(endpoints, day_obs_min, day_obs_max)

    bad_visits = Table()
    bad_visits['visit_id'] = bad_visit_ids
    bad_visits.write(args.output, overwrite=True)
    print(f"Wrote {len(bad_visits)} bad visits to {args.output}")
