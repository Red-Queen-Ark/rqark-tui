from rqark_app.agent.agents import AgentHoliday, Diana, Wednesday

AGENTS = [
    AgentHoliday(),
    Diana(),
    Wednesday()
]

PROVIDERS: list[dict] = [
    {
        "name": '',
        "model_name": '',
        "api_key": '',
        "api_base": '',
        "priority": 1
    }
]