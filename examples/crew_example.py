from langchain.llms import Ollama
from crewai import Agent, Task, Crew, Process


#ollama_openhermes = Ollama(model="openhermes")

researcher = Agent(
    role = 'Researcher',
    goal = 'Research latest human rights abuses that occured in the last month',
    backstory= 'you are a human rights researcher',
    verbose = True,
    allow_delegation = False,
    #llm=ollama_openhermes
)

writer = Agent(
    role = 'Writer',
    goal = 'Write a compelling and engaging blog post detailing the latest high profile human rights abuses in the last month with dates included',
    backstory= 'you are a top notch human rights writer',
    verbose=True,
    allow_delegation=False,
    #llm=ollama_openhermes
)

task1 = Task(description='investigate the latest human rights abuses', agent=researcher)
task2 = Task(description='write a compelling blog post about the latest human rights abuses', agent=writer)

crew = Crew(
    agents=[researcher, writer],
    tasks=[task1, task2],
    verbose=2,
    process=Process.sequential
)

result = crew.kickoff()


