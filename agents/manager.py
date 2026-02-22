import json
from typing import Dict, List, Optional
from langchain_core.language_models.chat_models import BaseChatModel
from agents.base import BaseAgent, AgentMessage, AgentState


class ManagerAgent(BaseAgent):
    """
    The Technical Lead Agent.
    Responsible for breaking down user requests, creating plans, and delegating tasks.
    """
    
    def __init__(self, llm: BaseChatModel):
        super().__init__(
            name="Tech Lead",
            role="Manager and System Architect",
            llm=llm
        )
        self.team: Dict[str, BaseAgent] = {}

    def register_agent(self, agent: BaseAgent):
        """Adds a developer agent to the manager's team."""
        self.team[agent.name] = agent

    def _format_system_prompt(self) -> str:
        prompt = super()._format_system_prompt()
        team_descriptions = "\n".join([f"- {name}: {agent.role}" for name, agent in self.team.items()])
        
        return f"""{prompt}
Your responsibilities:
1. Understand the user's high-level goal.
2. Formulate a step-by-step project plan.
3. Delegate specific tasks to your developer team members.
4. Review their work and synthesize a final response for the user.

Your team consists of:
{team_descriptions}

When delegating, output a JSON object with 'target_agent' and 'task_description'.
When finished, output a JSON object with 'final_response'.
"""

    async def process(self, message: AgentMessage, state: AgentState) -> AgentMessage:
        """Processes the input, either from the user or returning from a sub-agent."""
        
        # In a real implementation, we would pass the conversation history and state 
        # to the LLM to decide the next action (Delegate vs. Respond to User).
        
        system_prompt = self._format_system_prompt()
        
        # Simplified LLM interaction (mocking the internal routing)
        llm_prompt = f"""
Current State: {state.project_goal}
History: {[m.content for m in state.history][-3:]} 

New Message from {message.sender}: {message.content}

What is your next action? 
Respond with JSON: 
{{"action": "delegate", "target_agent": "AgentName", "task_description": "..."}} OR
{{"action": "respond", "final_response": "..."}}
"""
        response = self.llm.invoke(f"{system_prompt}\n\n{llm_prompt}")
        response_text = response.content
        
        try:
            # Parse the LLM's decision
            decision = json.loads(response_text)
            
            if decision.get("action") == "delegate":
                target = decision.get("target_agent")
                if target in self.team:
                    return AgentMessage(
                        sender=self.name,
                        receiver=target,
                        content=decision.get("task_description", "Please process this task.")
                    )
                else:
                    return AgentMessage(
                        sender=self.name,
                        receiver="User",
                        content=f"Error: I tried to delegate to {target}, but they are not on my team."
                    )
            else:
                return AgentMessage(
                    sender=self.name,
                    receiver="User",
                    content=decision.get("final_response", "Task complete.")
                )
                
        except json.JSONDecodeError:
            # Fallback if LLM doesn't output pure JSON
            return AgentMessage(
                sender=self.name,
                receiver="User",
                content=f"I processed the request but encountered an formatting issue. Raw output: {response_text}"
            )
