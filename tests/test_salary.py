"""Salary evidence, ingestion fallback, and non-destructive backfill."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from job_tools import job_history, prospects, manual_jobs, salary


class SalaryTests(unittest.TestCase):
    def test_ranges_periods_and_regions(self):
        for text in (
            'Base pay range (CA, WA, NY) per year: $195,000 - 255,000',
            'Salary: USD 100k–120k per year.',
            'Salary: £60,000 to £80,000 annually.',
            'Hourly pay: $35.50 per hour.',
            'Salary range\n$90,000–$110,000 per year',
            'Compensation is $189,000–$236,000 per year in Denver and $223,000–$278,000 per year in New York.',
        ):
            with self.subTest(text=text):
                result = salary.extract_salary(text)
                self.assertIsNotNone(result)
                self.assertEqual(result['salary_range'], text.replace('\n', ' '))
        result = salary.extract_salary('Salary in CA: $100,000–$150,000. Salary in NY: $110,000–$160,000.')
        self.assertEqual(len(result['evidence']), 2)

    def test_multiline_regional_salary_block(self):
        heading = 'Our target new hire base salary ranges for this role are the following:'
        text = heading + '\nUS employees (any location):\n$122,400—$158,400 USD\nCanadian employees (any location):\n$115,700—$149,700 CAD'
        result = salary.extract_salary(text)
        self.assertEqual(result['evidence'], [
            heading + ' US employees (any location): $122,400—$158,400 USD',
            heading + ' Canadian employees (any location): $115,700—$149,700 CAD',
        ])
        self.assertIsNone(salary.extract_salary('Base salary ranges:\nEquipment stipend:\n$1,000–$2,000'))
        self.assertIsNone(salary.extract_salary('Base salary ranges:\nWe also provide these benefits.\nUS employees:\n$1,000–$2,000'))

    def test_ignores_benefits_and_unqualified_money(self):
        for text in ('We raised $100,000-$200,000.', 'Salary competitive. Equipment stipend: $1,000-$2,000.',
                     'Compensation includes an insurance allowance of $100-$200 per month.',
                     'Salary: competitive', 'Salary 100000 to 150000',
                     'Fertility HRA (up to $10,000 per year)', '$10/week for Coffee with a Colleague',
                     'Annual Base Salary $1—$2 USD', 'Base pay: $163,944K - $215,176 per year'):
            self.assertIsNone(salary.extract_salary(text), text)

    def test_backfill_preview_apply_idempotence_and_pipeline(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(job_history, 'HISTORY_DB_PATH', Path(directory) / 'history.db'):
            path = Path(directory) / 'JOB_lever_test.json'
            url = 'https://jobs.lever.co/acme/11111111-1111-1111-1111-111111111111'
            path.write_text(json.dumps({'text': 'Engineer', 'hostedUrl': url, 'descriptionPlain': 'Base salary is $100,000-150,000 per year.'}))
            key = job_history.job_key(url)
            job_history.record_processed(url, str(path))
            facts = prospects.extract_and_save(url, str(path))
            self.assertIn('$100,000-150,000', facts['salary_range'])
            with job_history._database() as connection:
                connection.execute('UPDATE prospective_jobs SET salary_range = NULL, company = ? WHERE job_key = ?', ('Corrected Co', key))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(salary.backfill()['found'], 1)
                with job_history._database() as connection:
                    self.assertIsNone(connection.execute('SELECT salary_range FROM prospective_jobs').fetchone()[0])
                self.assertEqual(salary.backfill(apply=True)['updated'], 1)
                self.assertEqual(salary.backfill(apply=True)['scanned'], 0)
            with job_history._database() as connection:
                self.assertEqual(connection.execute('SELECT company FROM prospective_jobs').fetchone()[0], 'Corrected Co')
                connection.execute("UPDATE prospective_jobs SET salary_range = 'Existing salary'")
            prospects.extract_and_save(url, str(path))
            with job_history._database() as connection:
                self.assertEqual(connection.execute('SELECT salary_range FROM prospective_jobs').fetchone()[0], 'Existing salary')

    def test_manual_fallback(self):
        facts = manual_jobs.parse_posting('Job title: Engineer\nCompany: Acme\nBuild things.\nBase pay per year: $100,000 - 150,000')
        self.assertIn('$100,000 - 150,000', facts['salary_range'])
