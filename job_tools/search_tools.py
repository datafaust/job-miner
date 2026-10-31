from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import json
from pathlib import Path
from urllib.parse import urlencode
#from scrape_job import scrape_idealist_job_details
from crewai.tools import tool
from job_tools.job_history import filter_unprocessed
from job_tools.location import normalize_search_location
from job_tools.workflow_config import LIMITS
from selenium.webdriver.support.ui import WebDriverWait

def idealist_search_url(query, location, sort="relevance"):
    """Add the requested location to Idealist's keyword search."""
    query = query.strip()
    if not query:
        raise ValueError("Idealist search keywords are required")
    if not location.strip():
        raise ValueError("Idealist search location is required")
    if sort not in ("relevance", "newest"):
        raise ValueError("Idealist sort must be relevance or newest")
    location = normalize_search_location(location)
    if location == "remote":
        params = {"q": query, "locationType": "REMOTE"}
    else:
        params = {"q": f"{query} New York City"}
    if sort == "newest":
        params["sort"] = "newest"
    return f"https://www.idealist.org/en/jobs?{urlencode(params)}"


def idealist_shortlist(results):
    """Pass only the configured number of filtered results to the workflow."""
    return results[:LIMITS.idealist_candidates_per_run]


def prune_search_snapshot(path=Path("output.json")):
    """Remove jobs that became processed after the Idealist search was saved."""
    path = Path(path)
    if not path.exists():
        return 0
    results = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(results, list):
        raise ValueError("Idealist search snapshot must be a list")
    remaining = filter_unprocessed(results)
    path.write_text(json.dumps(remaining, ensure_ascii=False, indent=4), encoding="utf-8")
    return len(results) - len(remaining)


class SearchTools():

  @tool("Search the idealist website")
  def search_idealist(query, location, sort="relevance"):
    """Search Idealist and return a configured number of unprocessed jobs."""
    print("SEARCHING IDEALIST WITH THE QUERY...")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1200")

    driver = webdriver.Chrome(options=options)

    try:
        url = idealist_search_url(query, location, sort)
        driver.get(url)

        # Idealist loads results asynchronously; an empty page has its own marker.
        WebDriverWait(driver, 20).until(
            lambda page: page.find_elements(By.CSS_SELECTOR, '[data-qa-id="search-result"]')
            or page.find_elements(By.CSS_SELECTOR, '[data-qa-id="search-results-hits-empty"]')
        )
        elements_with_data_qa_id = driver.find_elements(By.CSS_SELECTOR, '[data-qa-id="search-result"]')
        #print(elements_with_data_qa_id)

        # Create a list to store the results
        results = []

        # Loop through elements_with_data_qa_id and append the text and link to the results list
        for element in elements_with_data_qa_id:
            # Get the text of the element
            element_text = element.text
            # Find the anchor tag within each element
            link_element = element.find_element(By.TAG_NAME, 'a')
            # Get the href attribute of the anchor tag
            link = link_element.get_attribute('href')
            # Append the text and link to the results list
            results.append({
                "text": element_text,
                "link": link
            })

        unprocessed_results = filter_unprocessed(results)
        shortlist = idealist_shortlist(unprocessed_results)
        print(
            f"Search recovered {len(results)} listings; "
            f"{len(unprocessed_results)} unprocessed; "
            f"{len(shortlist)} passed to the workflow."
        )

        # Keep a snapshot of the current search's unprocessed results.
        with open('output.json', 'w', encoding='utf-8') as file:
            json.dump(unprocessed_results, file, ensure_ascii=False, indent=4)

        return json.dumps(shortlist, ensure_ascii=False)

        # # Write the text of each element to a file
        # with open('output.txt', 'w', encoding='utf-8') as file:
        #     for element in elements_with_data_qa_id:
        #         element_text = element.text
        #         file.write(element_text + '\n')
        #         link = element.get_attribute('href')
        #         print(link)

        # # Find the link within the element
        #         link_element = element.find_element(By.TAG_NAME, 'a')
        #         link = link_element.get_attribute('href')
        #         file.write(f"Link: {link}\n\n")

    finally:
        driver.quit()

#query = "human rights researcher"
#SearchTools.search_idealist(query)



# import json
# import os

# import requests
# from langchain.tools import tool


# class SearchTools():

#   @tool("Search the internet")
#   def search_internet(query):
#     """Useful to search the internet 
#     about a a given topic and return relevant results"""
#     top_result_to_return = 4
#     url = "https://google.serper.dev/search"
#     payload = json.dumps({"q": query})
#     headers = {
#         'X-API-KEY': os.environ['SERPER_API_KEY'],
#         'content-type': 'application/json'
#     }
#     response = requests.request("POST", url, headers=headers, data=payload)
#     results = response.json()['organic']
#     stirng = []
#     for result in results[:top_result_to_return]:
#       try:
#         stirng.append('\n'.join([
#             f"Title: {result['title']}", f"Link: {result['link']}",
#             f"Snippet: {result['snippet']}", "\n-----------------"
#         ]))
#       except KeyError:
#         next

#     return '\n'.join(stirng)
