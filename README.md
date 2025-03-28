# mcp-cli

PoC cli that uses MCP-enabled reasoning-agent.

## Running

Uses the following MCPs:

- https://github.com/datalayer/jupyter-mcp-server: Interact with jupyter notebooks
- https://github.com/jnoller/condamcp: Interact with conda environments

- add `.env` with `OPENAI_API_KEY` environment variable and value
- install uv
- install docker and start docker daemon (used for jupyter-mcp-server)
- start jupyter if running jupyter-mcp-server: `uv run jupyter lab --port 8888 --IdentityProvider.token MY_TOKEN --ip 0.0.0.0`
- run cli: `make app`


## Issues

- Calling the `cleanup()` method in MCPManager freezes indefinitely when running `jupyter-mcp-server`. I'm not sure if this is because the MCP server lacks the necessary cleanup logic and/or if this has something to do with running MCP server via docker, but the result is that everytime the server is used it starts a new docker container and that container is never stopped.
- `jupyter-mcp-server` does not appear to give proper error messages when the jupyter notebook file is not found. Errors appear in the `jupyter lab` process (command shown above) but not in the information returned by the server; this results the ReasoningAgent continue 
