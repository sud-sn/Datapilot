from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from langchain_core.language_models.chat_models import BaseChatModel


class AgentMessage(BaseModel):
    """Represents a message passed between agents."""
    sender: str
    receiver: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=lambda: 0.0) # Placeholder


class AgentState(BaseModel):
    """Shared state / memory for the entire agent team."""
    project_goal: str = ""
    current_plan: str = ""
    tasks: Dict[str, str] = Field(default_factory=dict) # task_id -> status
    artifacts: Dict[str, Any] = Field(default_factory=dict) # e.g., generated code, test results
    history: List[AgentMessage] = Field(default_factory=list)


class BaseAgent(ABC):
    """
    Abstract base class for all DataPilot Developer Agents.
    Every agent in the MAS must implement this interface.
    """
    
    def __init__(self, name: str, role: str, llm: Optional[BaseChatModel] = None):
        self.name = name
        self.role = role
        # Some agents might need an LLM to perform their tasks
        self.llm = llm 

    @abstractmethod
    async def process(self, message: AgentMessage, state: AgentState) -> AgentMessage:
        """
        The core logic loop for the agent.
        
        Args:
            message: The incoming request or task from another agent (usually the Manager).
            state: The shared project state/memory.
            
        Returns:
            An AgentMessage containing the agent's response, output, or follow-up questions.
        """
        pass

    def _format_system_prompt(self) -> str:
        """Returns the foundational prompt that dictates the agent's persona and rules."""
        return f"You are {self.name}, the {self.role} for the DataPilot project."
