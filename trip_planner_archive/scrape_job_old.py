from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def scrape_idealist_job_details(url):
    options = Options()
    options.headless = True
    options.add_argument("--window-size=1920,1200")

    service = Service('/Users/fausto-personal/Documents/ai_projects/job-seeker-agent/chromedriver-mac-x64/chromedriver')  # Set the path to your chromedriver executable

    driver = webdriver.Chrome(service=service, options=options)

    try:
        driver.get(url)

        # # Find the element using the compound class name selector
        # element = driver.find_element(By.CSS_SELECTOR, ".sc-t050oh-0.jGPyck")

        # # Interact with the element (e.g., click, get text, etc.)
        # print(element.text)
        # Find the element using the provided XPath
        element = driver.find_element(By.XPATH, '//*[@id="layout-root"]/div[1]/div[6]/div')
        #element = driver.find_element(By.XPATH, '//*[@id="layout-root"]/div[1]/div[6]/div/div/div[3]/div[1]/div/div[1]/div')
        #xpath = '//*[@id="layout-root"]/div[1]/div[6]/div/div/div[3]/div[1]/div/div[1]/div/div/p[6]'
        #element = driver.find_element(By.XPATH, xpath)

        # Find the "Read more" button and click it
        read_more_button = driver.find_element(By.XPATH, '//*[@id="layout-root"]/div[1]/div[6]/div/div/div[3]/div[1]/div/div[3]/div/div/div/a')
        read_more_button.click()

        # Wait for the new content to load
        wait = WebDriverWait(driver, 10)
        new_content = wait.until(EC.visibility_of_element_located((By.XPATH, '//*[@id="layout-root"]/div[1]/div[6]/div/div/div[3]/div[1]/div/div[3]/div/div/div/a')))

        # Access the newly loaded content
        #print(new_content.text)

        # Find all <p> tags within the main element
        #p_tags = element.find_elements(By.TAG_NAME, 'p')

        # Interact with the element (e.g., get text, click, etc.)
        #print(element.text)
        element_text = element.text
        #print('below is the element text....')
        #print(element_text)

        # Write the element's text to a file
        # with open('element_text.txt', 'w', encoding='utf-8') as file:
        #     file.write(element.text)
        # Clean up the element text and generate a valid file name
        element_text = element.text.strip().replace('\n', ' ').replace('/', '_')  # Replace newline and slash with space and underscore
        file_name = f'JOB_{element_text[:40].strip().replace(" ", "_")}.txt'  # Replace spaces with underscores in the first 30 characters
        with open(file_name, 'w', encoding='utf-8') as file:
            file.write(element_text)

        #print(element_text)    

        return '\n'.join(element_text)


    finally:
        driver.quit()

# Example usage:
# url = "https://www.idealist.org/en/nonprofit-job/8a10b7bd05454fe1b631295eb611de92-director-policy-international-programs-access-now-brooklyn"

# url = "https://www.idealist.org/en/nonprofit-job/bcf832329bee4e819069b2b0ccef02a6-director-of-campus-affairs-flexible-within-the-us-ajc-new-york"
# scrape_idealist_job_details(url)


