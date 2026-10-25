"""Browser tool for reading Idealist job postings."""

import re
from pathlib import Path

from crewai.tools import tool
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from job_tools.job_history import extract_job_url, is_processed, job_key, record_processed
from job_tools.prospects import extract_and_save
from job_tools.relevance import is_relevant
from job_tools.search_tools import prune_search_snapshot


class BrowserTools:
    @tool("Scrape website content")
    def scrape_idealist_job_details(url, query=None):
        """Scrape an Idealist job. Input is its URL or a listing with a link field."""
        url = extract_job_url(url)
        if is_processed(url):
            return "This Idealist job was already processed; choose another result."

        print("SCRAPING DATA ...")
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1200")
        driver = webdriver.Chrome(options=options)

        try:
            driver.get(url)
            title = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'main [data-qa-id="listing-name"]')
                )
            )
            if not title.text.strip():
                raise ValueError("No job title was found on this page")

            main = driver.find_element(By.TAG_NAME, "main")
            for label in ("Read more about this job", "Read more about benefits"):
                controls = main.find_elements(
                    By.XPATH,
                    f'.//*[contains(@class, "show-more") and contains(normalize-space(.), "{label}")]',
                )
                if controls:
                    driver.execute_script("arguments[0].click()", controls[0])

            job_text = main.text.strip()
            if not job_text:
                raise ValueError("No job details were found on this page")

            for link in main.find_elements(By.TAG_NAME, "a"):
                if link.text.strip() == "Go to Website":
                    application_url = link.get_attribute("href")
                    if application_url:
                        job_text += f"\nApplication URL: {application_url}"
                    break

            if query and not is_relevant(query, title.text.strip(), job_text):
                print(f"Skipped unrelated Idealist job: {title.text.strip()} ({url})")
                return None

            safe_key = re.sub(r"[^A-Za-z0-9_-]", "_", job_key(url))[:100]
            job_dir = Path("jobs")
            job_dir.mkdir(exist_ok=True)
            file_path = job_dir / f"JOB_{safe_key}.txt"
            file_path.write_text(job_text, encoding="utf-8")
            record_processed(url, str(file_path))
            try:
                extract_and_save(url, str(file_path))
            except (OSError, ValueError, KeyError) as error:
                print(f"Could not extract prospective job fields for {url}: {error}")
            try:
                prune_search_snapshot()
            except (OSError, ValueError) as error:
                print(f"Could not refresh Idealist search snapshot: {error}")
            return job_text
        finally:
            driver.quit()
