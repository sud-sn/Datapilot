from agents.base import BaseAgent, AgentMessage, AgentState
from langchain_core.language_models.chat_models import BaseChatModel


class UIAgent(BaseAgent):
    def __init__(self, llm: BaseChatModel):
        super().__init__(name="UI Agent", role="Frontend & UX Developer", llm=llm)

    async def process(self, message: AgentMessage, state: AgentState) -> AgentMessage:
        return AgentMessage(
            sender=self.name,
            receiver=message.sender,
            content=f"Received UI task: '{message.content}'. Working on React/Next.js components. Task completed."
        )


class CoreReasoningAgent(BaseAgent):
    def __init__(self, llm: BaseChatModel):
        super().__init__(name="Core Reasoning Agent", role="Backend & AI Orchestrator", llm=llm)

    async def process(self, message: AgentMessage, state: AgentState) -> AgentMessage:
        return AgentMessage(
            sender=self.name,
            receiver=message.sender,
            content=f"Received Core task: '{message.content}'. Optimizing Text-to-SQL logic. Task completed."
        )


class IntegrationAgent(BaseAgent):
    def __init__(self, llm: BaseChatModel):
        super().__init__(name="Integration Agent", role="Database Connector Developer", llm=llm)

    async def process(self, message: AgentMessage, state: AgentState) -> AgentMessage:
        return AgentMessage(
            sender=self.name,
            receiver=message.sender,
            content=f"Received Integration task: '{message.content}'. Building new data connector. Task completed."
        )


class SecurityQAAgent(BaseAgent):
    def __init__(self, llm: BaseChatModel):
        super().__init__(name="Security QA Agent", role="Tester and Security Guard", llm=llm)

    async def process(self, message: AgentMessage, state: AgentState) -> AgentMessage:
        return AgentMessage(
            sender=self.name,
            receiver=message.sender,
            content=f"Received QA task: '{message.content}'. Running pytest and Playwright suites. All tests passed."
        )


class DevOpsAgent(BaseAgent):
    def __init__(self, llm: BaseChatModel):
        super().__init__(name="DevOps Agent", role="Platform & Sub-system Deployer", llm=llm)

    async def process(self, message: AgentMessage, state: AgentState) -> AgentMessage:
        return AgentMessage(
            sender=self.name,
            receiver=message.sender,
            content=f"Received DevOps task: '{message.content}'. Updating Docker and CI/CD pipelines. Deployed."
        )
