import asyncio
import os
from typing import Optional

from agents.base import AgentMessage, AgentState
from agents.manager import ManagerAgent
from agents.developers import (
    UIAgent, CoreReasoningAgent, IntegrationAgent, SecurityQAAgent, DevOpsAgent
)
from src.llm_providers import get_llm_provider
from src.config import Settings
settings = Settings()


class FakeLLM:
    """A mock LLM to demonstrate the message passing without API keys."""
    def __init__(self):
        self._turn = 0
        
    def invoke(self, prompt: str):
        self._turn += 1
        class Response:
            def __init__(self, content):
                self.content = content
        
        # Scripted responses to demonstrate the flow
        if self._turn == 1:
            return Response('{"action": "delegate", "target_agent": "DevOps Agent", "task_description": "Create Dockerfile and docker-compose.yml"}')
        elif self._turn == 2:
            return Response('{"action": "delegate", "target_agent": "Security QA Agent", "task_description": "Review the Docker setup"}')
        else:
            return Response('{"action": "respond", "final_response": "The Docker setup is complete and reviewed."}')


class AgentOrchestrator:
    """
    Manages the lifecycle and routing of messages for the Multi-Agent System.
    """
    
    def __init__(self):
        self.state = AgentState()
        self.llm = FakeLLM()  # Using Fake LLM for demonstration
        
        # Initialize Team
        self.manager = ManagerAgent(llm=self.llm)
        self.ui_agent = UIAgent(llm=self.llm)
        self.core_agent = CoreReasoningAgent(llm=self.llm)
        self.integration_agent = IntegrationAgent(llm=self.llm)
        self.qa_agent = SecurityQAAgent(llm=self.llm)
        self.devops_agent = DevOpsAgent(llm=self.llm)
        
        # Register Team to Manager
        self.manager.register_agent(self.ui_agent)
        self.manager.register_agent(self.core_agent)
        self.manager.register_agent(self.integration_agent)
        self.manager.register_agent(self.qa_agent)
        self.manager.register_agent(self.devops_agent)

    async def run(self, user_request: str) -> str:
        """
        Main entry point for a user request.
        The request goes to the Manager, who delegates to the team until complete.
        """
        self.state.project_goal = user_request
        
        # Create initial message from User -> Manager
        current_msg = AgentMessage(
            sender="User",
            receiver=self.manager.name,
            content=user_request
        )
        self.state.history.append(current_msg)
        
        print(f"\n[User Request]: {user_request}\n")
        
        # Event Loop
        max_turns = 10
        turn = 0
        
        while turn < max_turns:
            turn += 1
            
            # The Manager processes the message (either from User or returning from Node)
            print(f"[Turn {turn}] Manager is thinking...")
            manager_response = await self.manager.process(current_msg, self.state)
            self.state.history.append(manager_response)
            
            # If the Manager responded to the User, the task is complete
            if manager_response.receiver == "User":
                print(f"[Done] Manager replied to User: {manager_response.content}")
                return manager_response.content
                
            # Otherwise, the Manager delegated to a sub-agent
            target_agent_name = manager_response.receiver
            print(f"[Delegation] Manager -> {target_agent_name}: {manager_response.content}")
            
            # Find the target agent
            target_agent = self.manager.team.get(target_agent_name)
            if not target_agent:
                print(f"[System Error] Unknown agent: {target_agent_name}")
                break
                
            # Target agent processes the task
            print(f"         {target_agent_name} is working...")
            agent_response = await target_agent.process(manager_response, self.state)
            self.state.history.append(agent_response)
            
            # Sub-agent replies back to the Manager
            current_msg = agent_response
            print(f"[Result] {target_agent_name} -> Manager: {agent_response.content}\n")
            
        return "Task stopped: Reached maximum turns."


async def run_simulation():
    """Runs a hardcoded simulation to test the MAS flow."""
    import dotenv
    dotenv.load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    orchestrator = AgentOrchestrator()
    await orchestrator.run("DataPilot needs Docker support. Create a Dockerfile and docker-compose.yml.")

if __name__ == "__main__":
    asyncio.run(run_simulation())
