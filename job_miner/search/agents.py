from crewai import Agent, LLM

class JobAgents():

  def __init__(self, model="openhermes"):
    self.llm = LLM(model=f"ollama/{model}", base_url="http://localhost:11434")

  def job_selection_agent(self):
    return Agent(
        role='Job Selection Expert',
        goal='Find the jobs best suited for this person to apply to',
        backstory='An expert in helping people find the jobs they are looking for',
        allow_delegation=False,
        verbose=True
        ,llm=self.llm
        )
  
  def job_information_organizer(self):
    return Agent(
        role='Job Information Organization Expert',
        goal='Parse through the job information provided to you and organize it for the client',
        backstory="""A knowledgeable employment consultant who knows how to organize information.""",
        allow_delegation=False,
        # tools=[
        #     SearchTools.search_internet,
        #     BrowserTools.scrape_and_summarize_website,
        # ],
        verbose=True
        ,llm=self.llm
        )
  
