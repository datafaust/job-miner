"""List job categories or all title phrases in config/related_keys.json."""

import argparse

from job_tools.relevance import load_related_keys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all-titles", action="store_true",
        help="Include primary and related title phrases, removing duplicates.",
    )
    args = parser.parse_args()
    try:
        profiles = load_related_keys()
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    titles = set(profiles)
    if args.all_titles:
        for profile in profiles.values():
            titles.update(profile["primary_title_phrases"])
            titles.update(profile["related_title_phrases"])
    for title in sorted(titles):
        print(title)


if __name__ == "__main__":
    main()
