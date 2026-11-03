"""Check saved postings without AI or paid APIs."""
import argparse
import json
from job_tools.availability import audit


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--force', action='store_true', help='Recheck jobs checked within the last 24 hours')
    parser.add_argument('--boards-only', action='store_true', help='Skip individual page checks for other sources')
    args = parser.parse_args(argv)
    print(json.dumps(audit(force=args.force, pages=not args.boards_only), indent=2))


if __name__ == '__main__':
    main()
