"""Compact salary display prefers NY and preserves evidence in storage."""
import unittest
from job_tools.salary import format_salary
from job_tools import job_history
from tests import test_job_web


class SalaryDisplayTests(unittest.TestCase):
    def test_regional_preference(self):
        heading = 'Our target new hire base salary ranges for this role are the following: '
        text = heading + 'US employees (any location): $122,400—$158,400 USD | ' + heading + 'Canadian employees (any location): $115,700—$149,700 CAD'
        self.assertEqual(format_salary(text), '$122,400–$158,400 USD')
        self.assertEqual(format_salary('US: $100k-$140k/year | New York: $120k-$160k/year'), '$120,000–$160,000/year')
        self.assertEqual(format_salary('Compensation is $100k-$140k per year in Denver and $120k-$160k per year in San Francisco and New York.'), '$120,000–$160,000/year')
        self.assertEqual(format_salary('US: $100k-$140k | Outside of New York: $90k-$110k'), '$100,000–$140,000')

    def test_units_and_ambiguous_regions(self):
        self.assertEqual(format_salary('$35.50 per hour'), '$35.50/hour')
        self.assertEqual(format_salary('USD 100k–120k annually'), '$100,000–$120,000 USD/year')
        self.assertEqual(format_salary('$6,250/month'), '$6,250/month')
        self.assertEqual(format_salary('California: $100k-$140k | Washington: $110k-$150k'), '$100,000–$140,000 (California) | $110,000–$150,000 (Washington)')
        self.assertEqual(format_salary('Canada: $100k-$140k CAD'), 'No US salary listed')
        self.assertEqual(format_salary('Competitive'), 'Competitive')
        self.assertEqual(format_salary(None), '—')
        self.assertEqual(format_salary('$100,000 - $120,000 (Adzuna estimate)'), '$100,000–$120,000 (Adzuna estimate)')


class SalaryDisplayWebTests(unittest.TestCase):
    setUp = test_job_web.JobWebTests.setUp
    save_idealist = test_job_web.JobWebTests.save_idealist

    def test_shared_formatter_does_not_change_saved_evidence(self):
        key = self.save_idealist('a' * 32, 'Important Job')
        original = 'Base salary ranges: US employees: $122,400—$158,400 USD | Base salary ranges: Canadian employees: $115,700—$149,700 CAD'
        with job_history._database() as connection:
            connection.execute('UPDATE prospective_jobs SET salary_range=? WHERE job_key=?', (original, key))
        for route in ('/', f'/jobs/{key}'):
            page = self.client.get(route)
            self.assertEqual(page.status_code, 200)
            self.assertIn('$122,400–$158,400 USD'.encode(), page.data)
            self.assertNotIn(b'Canadian employees', page.data)
        with job_history._database() as connection:
            self.assertEqual(connection.execute('SELECT salary_range FROM prospective_jobs WHERE job_key=?', (key,)).fetchone()[0], original)
