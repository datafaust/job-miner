"""Conservative, source-backed salary extraction and missing-salary backfill.

Run ``python -m job_tools.salary`` to preview; add ``--apply`` to save.
"""
import argparse
import json
import re

from job_tools import job_history

MONEY = r'(?:USD|CAD|AUD|GBP|EUR|US\$|CA\$|A\$|[$£€])'
NUMBER = r'\d+(?:,\d{3})*(?:\.\d+)?[kK]?'
RANGE = re.compile(
    rf'(?<![\w,]){MONEY}\s*{NUMBER}\s*(?:-|–|—|to)\s*(?:{MONEY}\s*)?{NUMBER}(?![\w,])', re.I)
SINGLE = re.compile(rf'{MONEY}\s*{NUMBER}\s*(?:(?:/|per\s+)(?:hour|hr|year|yr|month|week)|annually|hourly)\b', re.I)
PAY = re.compile(r'\b(?:salary|salaries|compensation|base pay|pay range|pay rate|annual pay|hourly pay|hourly range|retainer|wage)\b', re.I)
NON_PAY = re.compile(r'\b(?:bonus|equity|stock|stipend|budget|reimbursement|allowance|revenue|funding|insurance|401k|401\(k\))\b', re.I)


def extract_salary(text):
    """Return salary and exact source excerpts, or None when uncertain.

    Preserve regional ranges and pay periods in their original context. Never
    annualize, infer currency, or select one regional range over another.
    """
    # Normalize whitespace only; retain wording, currency and regional labels.
    text = re.sub(r'[^\S\n]+', ' ', text)
    chunks = re.split(r'\n+|(?<=[.!?])\s+(?=[A-Z])', text)
    # A compensation heading may introduce several location/range pairs.
    # Carry it only through short labels and amount lines, never across prose
    # or a benefits heading.
    expanded = []
    heading = ''
    label = ''
    remaining = 0
    for chunk in chunks:
        chunk = chunk.strip()
        has_amount = RANGE.search(chunk) or SINGLE.search(chunk)
        if PAY.search(chunk) and not has_amount and len(chunk) < 150 and chunk.endswith(':') and not NON_PAY.search(chunk):
            heading, label, remaining = chunk, '', 8
        elif heading and remaining and has_amount:
            expanded.append(' '.join(part for part in (heading, label, chunk) if part))
            label = ''
            remaining -= 1
            continue
        elif heading and remaining and len(chunk) < 100 and chunk.endswith(':') and not NON_PAY.search(chunk):
            label = chunk
            remaining -= 1
        else:
            heading, label, remaining = '', '', 0
        expanded.append(chunk)
    chunks = expanded
    evidence = []
    previous = ''
    for chunk in chunks:
        chunk = chunk.strip()
        matches = list(RANGE.finditer(chunk)) + list(SINGLE.finditer(chunk))
        if not matches or len(chunk) > 1200:
            previous = chunk
            continue
        # Reject malformed or placeholder amounts for the whole excerpt, so a
        # valid-looking upper endpoint cannot rescue an invalid range.
        amounts = [amount for match in matches for amount in re.findall(NUMBER, match.group())]
        if any(float(amount.rstrip('kK').replace(',', '')) < 5 or
               (amount[-1:] in {'k', 'K'} and float(amount[:-1].replace(',', '')) > 1000)
               for amount in amounts):
            previous = chunk
            continue
        heading = previous if len(previous) < 100 and PAY.search(previous) and not RANGE.search(previous) and not SINGLE.search(previous) else ''
        context = (heading + ' ' + chunk).strip()
        accepted = False
        for match in matches:
            before = chunk[max(0, match.start() - 100):match.start()]
            # A nearby benefit label takes precedence over an earlier salary label.
            pay = list(PAY.finditer(before))
            other = list(NON_PAY.finditer(before))
            if other and (not pay or other[-1].end() > pay[-1].end()):
                continue
            if PAY.search(context):
                accepted = True
        if accepted and context not in evidence:
            evidence.append(context)
        previous = chunk
    if not evidence:
        return None
    # Store source wording rather than stripping away location/period qualifiers.
    return {'salary_range': ' | '.join(evidence), 'evidence': evidence}


def backfill(*, apply=False):
    """Only update existing fact rows with blank salary; never reparse other facts."""
    from job_tools.resume_inputs import load_saved_posting
    with job_history._database() as connection:
        rows = connection.execute("""SELECT p.job_key FROM prospective_jobs p
            JOIN processed_jobs h USING (job_key)
            WHERE NULLIF(TRIM(p.salary_range), '') IS NULL ORDER BY p.job_key""").fetchall()
    counts = dict(scanned=len(rows), found=0, updated=0, unresolved=0, errors=0)
    for (key,) in rows:
        try:
            result = extract_salary(load_saved_posting(key)['posting_text'])
        except (OSError, ValueError, KeyError, UnicodeError) as error:
            counts['errors'] += 1
            print(json.dumps({'job_key': key, 'error': str(error)}))
            continue
        if result is None:
            counts['unresolved'] += 1
            continue
        counts['found'] += 1
        if apply:
            with job_history._database() as connection:
                updated = connection.execute("""UPDATE prospective_jobs SET salary_range = ?
                    WHERE job_key = ? AND NULLIF(TRIM(salary_range), '') IS NULL""",
                    (result['salary_range'], key)).rowcount
                counts['updated'] += updated
        print(json.dumps({'job_key': key, **result}, ensure_ascii=False))
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Save missing salaries (default: preview only).')
    args = parser.parse_args()
    print(json.dumps({'summary': backfill(apply=args.apply)}))


# Display formatting is separate from extraction: saved evidence stays intact.
_DISPLAY_AMOUNT = rf'(?:{MONEY}\s*)?{NUMBER}'
_PERIOD = r'(?:\s*(?:/\s*|per\s+)(?:year|yr|hour|hr|month|week)|\s+(?:annually|hourly))'
_DISPLAY_RANGE = re.compile(
    rf'(?<![\w,]){MONEY}\s*{NUMBER}(?:{_PERIOD})?\s*(?:-|–|—|to)\s*{_DISPLAY_AMOUNT}(?:{_PERIOD})?', re.I)
_NY = re.compile(r'\b(?:New York(?: City)?|NYC|NY)\b', re.I)
_US = re.compile(r'\b(?:US|USA|United States|U\.S\.|US-wide)\b', re.I)
_FOREIGN = re.compile(r'\b(?:Canada|Canadian|CAD|EUR|GBP|AUD|UK|United Kingdom|Europe|Germany|France|Australia|India)\b|[£€]', re.I)
_REGION = re.compile(r'\b(?:CA|California|WA|Washington|NJ|New Jersey|CT|Connecticut|Denver|Colorado|San Francisco|Seattle|Los Angeles|NYC|NY|New York|US|USA|United States|Canada|Canadian|Toronto|Zone\s+\d)\b', re.I)


def format_salary(value):
    """Compact salary display, preferring explicit NY then US-wide evidence.

    Unknown units and currencies stay unknown. Ambiguous US regions retain
    their labels; unsupported formats retain the original saved value.
    """
    if not value or not value.strip():
        return '—'
    candidates = []
    for part in re.split(r'\s*\|\s*|\n+|;\s*', value):
        matches = list(_DISPLAY_RANGE.finditer(part))
        if not matches:
            matches = list(SINGLE.finditer(part))
        for index, match in enumerate(matches):
            before = part[matches[index - 1].end() if index else 0:match.start()].strip(' ,.')
            after = part[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(part)].strip(' ,.')
            # A suffix such as "per year in Denver" belongs to this amount;
            # a following "US base pay range:" heading belongs to the next.
            suffix_region = re.search(r'^(?:(?:USD|CAD)\b[ .]*)?(?:per\s+(?:year|hour|month)\s+)?(?:in|for)\s+(.+)', after, re.I)
            region = suffix_region.group(1).strip(' ,.') if suffix_region else before
            region = re.sub(r'\s*(?:and|,)?\s*(?:the )?(?:base )?(?:salary|pay|compensation)\s*(?:range)?.*$', '', region, flags=re.I) if not _REGION.search(region) else region
            currency_text = match.group() + ' ' + after[:10]
            if _FOREIGN.search(region + ' ' + currency_text):
                continue
            # Explicit exclusions do not count as NY matches.
            excluded_ny = re.search(r'\b(?:outside(?: of)?|excluding|except)\b.*', region, re.I)
            ny = bool(_NY.search(region)) and not (excluded_ny and _NY.search(excluded_ny.group()))
            us_wide = bool(_US.search(region)) and not _REGION.search(_US.sub('', region))
            rank = 3 if ny else 2 if us_wide else 1 if not _REGION.search(region) else 0
            numbers = re.findall(NUMBER, match.group())
            def number(raw):
                from decimal import Decimal
                amount = Decimal(raw.rstrip('kK').replace(',', ''))
                if raw[-1:] in {'k', 'K'}:
                    amount *= 1000
                return f'{amount:,.0f}' if amount == amount.to_integral() else f'{amount:,.2f}'
            symbol = '€' if '€' in match.group() else '£' if '£' in match.group() else '$'
            compact = '–'.join(symbol + number(n) for n in numbers)
            currency = re.search(r'\b(?:USD|CAD|AUD|GBP|EUR)\b', match.group() + ' ' + after[:10], re.I)
            if currency:
                compact += ' ' + currency.group().upper()
            unit_text = match.group() + ' ' + (before if len(matches) == 1 else '') + ' ' + after[:35]
            unit = re.search(r'(?:/\s*|per\s+)(year|yr|hour|hr|month|week)\b|\b(annual(?:ly)?|hourly)\b', unit_text, re.I)
            if unit:
                raw_unit = (unit.group(1) or unit.group(2)).lower()
                compact += '/' + {'yr': 'year', 'hr': 'hour', 'annual': 'year', 'annually': 'year', 'hourly': 'hour'}.get(raw_unit, raw_unit)
            if rank == 0:
                label = region
                # Drop the introductory prose while preserving the region clause.
                label = (re.split(r':\s*', label)[-1] or region).rstrip(': ')
                compact += f' ({label})'
            if re.search(r'Adzuna estimate', part, re.I):
                compact += ' (Adzuna estimate)'
            if re.search(r'\b(?:on target|on-target|OTE|total compensation)\b', part, re.I):
                compact += ' (total compensation)'
            candidates.append((rank, compact))
    if not candidates:
        return 'No US salary listed' if _FOREIGN.search(value) else value.strip()
    best = max(rank for rank, _ in candidates)
    return ' | '.join(dict.fromkeys(text for rank, text in candidates if rank == best))


if __name__ == '__main__':
    main()
