"""A Textual app that acts as a chat terminal with a reasoning agent and CLI capabilities."""
from copy import deepcopy
from pathlib import Path
from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer, Container
from textual.widgets import TextArea, Static
import subprocess
import json
import asyncio
from sik_llms import TextResponse, create_client, user_message, TextChunkEvent
from sik_llms.models_base import (
   assistant_message, system_message, ThinkingEvent,
   ToolPredictionEvent, ToolResultEvent, ErrorEvent,
)
from sik_llms.reasoning_agent import ReasoningAgent
from sik_llms.mcp_manager import MCPClientManager
from rich.markup import escape

PROJECT_DIR = Path(__file__).parent.parent
NOTEBOOK_PATH = PROJECT_DIR / 'mcp' / 'mcp_test.ipynb'
assert NOTEBOOK_PATH.exists(), f"Notebook path {NOTEBOOK_PATH} does not exist."
MCP_SERVERS_CONFIG = {
    "mcpServers": {
        "jupyter": {
            "command": "/usr/local/bin/docker",
            "args": [
                "run",
                "-i",
                "--rm",
                "-e",
                "SERVER_URL",
                "-e",
                "TOKEN",
                "-e",
                "NOTEBOOK_PATH",
                "datalayer/jupyter-mcp-server:latest",
            ],
            "env": {
                "SERVER_URL": "http://host.docker.internal:8888",
                "TOKEN": "MY_TOKEN",
                "NOTEBOOK_PATH": str(NOTEBOOK_PATH),
            },
        },
        "Conda": {
            "command": subprocess.check_output(["which", "uv"], text=True).strip(),
            "args": ["run", "condamcp"],
        },
    },
}
DEFAULT_MESSAGES = [system_message("You are a CLI conda assistant. Give helpful and detailed but concise replies. Prefer conda over pip when possible.")]  # noqa: E501


class CustomTextArea(TextArea):  # noqa: D101
    async def _on_key(self, event) -> None:  # noqa: ANN001
        if event.key == "enter" and self.app.multiline_mode:
            await super()._on_key(event)
        elif event.key == "enter":
            event.prevent_default()
            event.stop()
            await self.app.handle_submission(self.text)
        else:
            await super()._on_key(event)


def aggresive_escape(text: str | object) -> str:
    """Escapes characters that would interfere with Textual's markup syntax."""
    # # First replace newlines with spaces to prevent markup parsing issues
    # text = text.replace('\n', ' ')
    # # Then escape other special characters
    text = str(text)
    text = text.replace('[', r'\[') \
        .replace(']', r'\]') \
        .replace('\\[', r'\\[') \
        .replace('\\]', r'\\]') \
        .replace('{', r'\{') \
        .replace('}', r'\}') \
        .replace('|', r'\|') \
        .replace('"', r'\"') \
        .replace("'", r"\'")
    return escape(text)


class ChatTerminalApp(App):  # noqa: D101
    CSS = """
    Screen {
        layers: base overlay;
        background: white;
        color: black;
    }

    .output-container {
        height: 85%;
        border: solid green;
        margin: 0;
        padding: 1;
        overflow-y: auto;
        scrollbar-gutter: stable;
        overflow-x: hidden;
    }

    .status-container {
        height: 1;
        margin: 0;
        padding-left: 1;
    }

    .input-container {
        height: 12%;
        margin: 0;
        padding: 0;
    }

    .instructions-container {
        height: 1;
        margin: 0;
        padding-left: 1;
        padding-bottom: 0;
    }

    TextArea {
        background: white;
        color: black;
        border: solid blue;
    }

    TextArea.terminal-mode {
        border: solid red;
        background: #2b2b2b;
        color: #ffffff;
    }

    TextArea.agent-mode {
        border: solid purple;
        background: white;
        color: black;
    }

    #output {
        width: 100%;
        background: white;
        color: black;
        border: none;
    }

    #status {
        text-align: left;
    }

    #instructions {
        text-align: left;
        color: #666666;
    }
    """


    def __init__(self):
        super().__init__()
        self.mode = "chat"
        self.multiline_mode = False
        self.output_content = ""
        self.messages = deepcopy(DEFAULT_MESSAGES)


    def compose(self) -> ComposeResult:  # noqa: D102
        with ScrollableContainer(classes="output-container") as output_container:  # noqa: F841
            yield Static(id="output")
        with Container(classes="status-container"):
            yield Static("MODE: chat | ENTER: submit", id="status")
        with Container(classes="input-container"):
            yield CustomTextArea(id="input")
        with Container(classes="instructions-container"):
            yield Static("cntr+t to toggle modes (Chat, Terminal, Agent); cntr+l to change 'enter' key behavior", id="instructions")  # noqa: E501


    def update_status(self) -> None:  # noqa: D102
        mode_text = "terminal" if self.mode == "terminal" else ("agent" if self.mode == "agent" else "chat")  # noqa: E501
        input_text = "new-line" if self.multiline_mode else "submit"
        self.query_one("#status").update(f"MODE: {mode_text} | ENTER: {input_text}")

        # Add or remove mode classes based on mode
        input_area = self.query_one("#input")
        input_area.remove_class("terminal-mode")
        input_area.remove_class("agent-mode")

        if self.mode == "terminal":
            input_area.add_class("terminal-mode")
            input_area.placeholder = "$ "
        elif self.mode == "agent":
            input_area.add_class("agent-mode")
            input_area.placeholder = "Ask the agent..."
        else:
            input_area.placeholder = ""


    async def on_key(self, event) -> None:  # noqa: ANN001, D102
        if event.key == "ctrl+c":
            self.exit()
        elif event.key == "ctrl+t":
            # Cycle through modes: chat -> terminal -> agent -> chat
            if self.mode == "chat":
                self.mode = "terminal"
            elif self.mode == "terminal":
                self.mode = "agent"
            else:
                self.mode = "chat"
            self.update_status()
        elif event.key == "ctrl+l":
            self.multiline_mode = not self.multiline_mode
            self.update_status()


    async def handle_submission(self, text: str) -> None:  # noqa: D102, PLR0915
        if not text.strip():
            return

        output = self.query_one("#output", Static)
        input_area = self.query_one("#input", TextArea)
        input_area.clear()
        scroll_container = self.query_one(ScrollableContainer)
        if text.strip() == "clear":
            output.update("")
            self.output_content = ""
            self.messages = deepcopy(DEFAULT_MESSAGES)
            return
        if self.mode == "chat":
            # Add user message
            self.messages.append(user_message(text))
            if self.output_content:
                self.output_content += "\n"
            self.output_content += f"[blue]USER:[/blue]\n{aggresive_escape(text)}\n\n[green]ASSISTANT:[/green]\n"  # noqa: E501
            output.update(self.output_content)


            # Create client and message
            client = create_client(
                model_name='gpt-4o-mini',
                temperature=0.1,
            )

            # Create a task for streaming
            async def stream_response() -> None:
                response = ""
                async for event in client.stream(messages=self.messages):
                    if isinstance(event, TextChunkEvent):
                        self.output_content += aggresive_escape(event.content)
                        response += event.content
                        output.update(self.output_content)
                        scroll_container.scroll_end(animate=False)
                self.output_content += "\n"
                self.messages.append(assistant_message(response))


            # Start streaming in a separate task
            asyncio.create_task(stream_response())  # noqa: RUF006


        elif self.mode == "agent":
            # Add user message
            if self.output_content:
                self.output_content += "\n"
            self.output_content += f"[blue]USER:[/blue]\n{aggresive_escape(text)}\n\n[green]AGENT:[/green]\n"  # noqa: E501
            output.update(self.output_content)


            # Create a task for agent streaming
            async def stream_agent_response() -> None:  # noqa: PLR0915
                tools = []
                mcp_manager = MCPClientManager(configs=MCP_SERVERS_CONFIG)
                await mcp_manager.connect_servers()
                tools = mcp_manager.get_tools()
                try:
                    # Stream the agent's response
                    agent = ReasoningAgent(
                        model_name='gpt-4o',
                        tools=tools,
                        max_iterations=10,
                        temperature=0.1,
                    )
                    current_iteration = 0
                    message_content = ""
                    async for event in agent.stream(messages=[user_message(text)]):
                        if isinstance(event, ThinkingEvent):
                            if hasattr(event, 'iteration') and event.iteration != current_iteration:  # noqa: E501
                                current_iteration = event.iteration
                            if event.content:
                                self.output_content += f"\n[orange]|THINKING|:[/orange]\n{aggresive_escape(event.content)}\n"  # noqa: E501
                                message_content += f"\n|THINKING|:\n{event.content}\n"

                        elif isinstance(event, ToolPredictionEvent):
                            self.output_content += "\n[purple]|TOOL PREDICTION|:[/purple]\n"
                            self.output_content += f"Tool: `{aggresive_escape(event.name)}`\n"
                            self.output_content += f"Parameters:\n```json\n{aggresive_escape(json.dumps(event.arguments, indent=2))}\n```\n"  # noqa: E501
                            message_content += "\n|TOOL PREDICTION|:\n"
                            message_content += f"Tool: `{event.name}`\n"
                            message_content += f"Parameters:\n```json\n{json.dumps(event.arguments, indent=2)}\n```\n"  # noqa: E501


                        elif isinstance(event, ToolResultEvent):
                            self.output_content += "\n[purple]|TOOL RESULT|:[/purple]\n"
                            self.output_content += f"Tool: `{aggresive_escape(event.name)}`\n"
                            self.output_content += f"Result: {aggresive_escape(event.result)}\n"
                            message_content += "\n|TOOL RESULT|:\n"
                            message_content += f"Tool: `{event.name}`\n"
                            message_content += f"Result: {event.result!s}\n"


                        elif isinstance(event, ErrorEvent):
                            with open("error.log", "a") as f:  # noqa: ASYNC230
                                f.write(f"Error: {event!s}\n")
                            self.output_content += "\n[red]|ERROR|:[/red]\n"
                            self.output_content += f"Error: {aggresive_escape(str(event.content))}\n"  # noqa: E501
                            message_content += "\n|ERROR|:\n"
                            message_content += f"Error: {event.content!s}\n"


                        elif isinstance(event, TextChunkEvent):
                            if current_iteration >= 0:  # Only print header once
                                self.output_content += "\n[green]|FINAL RESPONSE|:[/green]\n"
                                message_content += "\n|FINAL RESPONSE|:\n"
                                current_iteration = -1  # Prevent header from showing again
                            self.output_content += aggresive_escape(event.content)
                            message_content += event.content
                        elif isinstance(event, TextResponse):
                            pass
                        else:
                            raise ValueError(f"Unknown event type: {type(event)}")
                        output.update(self.output_content)
                        scroll_container.scroll_end(animate=False)
                    self.output_content += "\n"
                    self.messages.append(assistant_message(message_content))
                except Exception as e:
                    # write error to file
                    with open("error.log", "a") as f:  # noqa: ASYNC230
                        f.write(f"Error 3: {e!s}\n")
                    self.output_content += f"\n\n[red]ERROR: {aggresive_escape(str(e))}[/red]\n"
                    output.update(self.output_content)
                    self.messages.append(assistant_message(f"Error: {e!s}"))
                # finally:
                    # output.update(self.raw_content + "\n\n[magenta]CLEANING UP[/magenta]\n")
                    # await mcp_manager.cleanup()
                    # output.update(self.raw_content + "\n\n[magenta]CLEANED UP[/magenta]\n")

            def handle_task_exception(task) -> None:  # noqa: ANN001
                try:
                    # This will re-raise any exception that occurred
                    task.result()
                except Exception as e:
                    with open("error.log", "a") as f:
                        f.write(f"Error 1: {e!s}\n")
                    self.output_content += f"\n\n[red]ERROR: {aggresive_escape(str(e))}[/red]\n"
                    output = self.query_one("#output", Static)
                    output.update(self.output_content)
                    self.messages.append(assistant_message(f"Error: {e!s}"))
            task = asyncio.create_task(stream_agent_response())
            task.add_done_callback(handle_task_exception)

        else:
            try:
                result = subprocess.run(  # noqa: ASYNC221
                    text,
                    capture_output=True,
                    text=True,
                    shell=True, check=False,
                )
                output_text = result.stdout if result.stdout else result.stderr
                if self.output_content:
                    self.output_content += "\n"
                # Escape special characters and use Textual's markup for terminal output
                escaped_output = aggresive_escape(output_text)
                content = f"$ {text}\n[monospace]{escaped_output}[/monospace]"
                self.output_content += content
                self.messages.append(user_message("[PREVIOUS COMMAND]\n\n" + content))
                output.update(self.output_content)
            except Exception as e:
                with open("error.log", "a") as f:  # noqa: ASYNC230
                    f.write(f"Error 2: {e!s}\n")
                if self.output_content:
                    self.output_content += "\n"
                self.output_content += f"Error: {e!s}"
                output.update(self.output_content)
        scroll_container.scroll_end(animate=False)


if __name__ == "__main__":
   app = ChatTerminalApp()
   app.run()
