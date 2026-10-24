from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import json
#from scrape_job import scrape_idealist_job_details
import time
import random
from langchain.tools import tool


class SearchTools():

  @tool("Search the idealist website")
  def search_idealist(query):
    """Useful to search the internet 
    about a a given topic and return relevant results"""
    top_result_to_return = 2
    options = Options()
    options.headless = True
    options.add_argument("--window-size=1920,1200")

    service = Service('/Users/fausto-personal/Documents/ai_projects/job-seeker-agent/chromedriver-mac-x64/chromedriver')  # Set the path to your chromedriver executable

    driver = webdriver.Chrome(service=service, options=options)

    try:
        url = f"https://www.idealist.org/en/jobs?q={query}"
        driver.get(url)

        # Find elements with data-qa-id="search-results"
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

        # Write the results to a JSON file
        with open('output.json', 'w', encoding='utf-8') as file:
            json.dump(results, file, ensure_ascii=False, indent=4)

        #print(results)

        # Loop through the top 5 results and scrape each job details page
        for index, result in enumerate(results[:top_result_to_return]):
            # Sleep for a random time between 1 and 5 seconds
            sleep_time = random.uniform(1, 5)
            time.sleep(sleep_time)
            url = result['link']
            #scrape_idealist_job_details(url)
            print(f"Scraped job details for result {index + 1} here: {url}")

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

# Example usage:
#query = "human rights researcher"
#SearchTools.search_idealist(query)
#scrape_idealist_jobs(query)





# from selenium import webdriver
# from selenium.webdriver.chrome.service import Service
# from selenium.webdriver.common.by import By
# from selenium.webdriver.chrome.options import Options
# from selenium.webdriver.support.ui import WebDriverWait
# from selenium.webdriver.support import expected_conditions as EC
# import time

# def scrape_idealist_jobs(query):
#     options = Options()
#     options.add_argument("--headless")  # Run Chrome in headless mode (no GUI)
#     service = Service('/Users/fausto-personal/Documents/ai_projects/job-seeker-agent/chromedriver-mac-x64/chromedriver')  # Set the path to your chromedriver executable
#     driver = webdriver.Chrome(service=service, options=options)

#     try:
#         url = f"https://www.idealist.org/en/jobs?q={query}"
#         driver.get(url)

#         # Wait for job listings to load
#         #WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, 'sc-1ic33xd-0 hgazvy')))

#         # Find all job listings on the page
#         job_listings = driver.find_elements(By.CSS_SELECTOR, '[data-qa-id="search-results-body"]')
#         print(job_listings)


#         # Print job details
#         for job in job_listings:
#             title = job.find_element(By.CLASS_NAME, 'title-link').text.strip()
#             organization = job.find_element(By.CLASS_NAME, 'entity-info').text.strip()
#             location = job.find_element(By.CLASS_NAME, 'location').text.strip()
#             date_posted = job.find_element(By.CLASS_NAME, 'date').text.strip()

#             print(f"Title: {title}")
#             print(f"Organization: {organization}")
#             print(f"Location: {location}")
#             print(f"Date Posted: {date_posted}")
#             print("")

#     finally:
#         driver.quit()

# # Example usage:
# query = "human rights activist"
# scrape_idealist_jobs(query)





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
