"""Invoke the real stdio server without starting MATLAB or reading user files."""

import asyncio
import json
import sys
import tempfile

from jsonschema import validate
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check():
    with tempfile.TemporaryDirectory(prefix="matlab-mcp-smoke-") as root:
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "matlab_companion", "serve", "--root", root]
        )
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            listing = await session.list_tools()
            assert len(listing.tools) == 6
            schemas = {tool.name: tool.output_schema for tool in listing.tools}
            for name, args in [
                ("matlab_status", {}),
                ("matlab_help", {}),
                (
                    "matlab_artifacts",
                    {"action": "read_schema", "operation": "linear_calibration"},
                ),
                (
                    "matlab_run",
                    {
                        "operation": "linear_calibration",
                        "parameters": {},
                        "idempotency_key": "invalid",
                    },
                ),
            ]:
                result = await session.call_tool(name, args)
                validate(result.structured_content, schemas[name])
                assert json.loads(result.content[0].text) == result.structured_content
                if name == "matlab_run":
                    assert result.is_error and not result.structured_content["ok"]
            resources = await session.list_resources()
            assert len(resources.resources) == 10
            await session.read_resource("matlab-companion://schemas/linear_calibration/result")
    print(
        "PASS: real stdio initialize/list/call/resources, six output schemas, JSON fallback and invalid request."
    )


if __name__ == "__main__":
    asyncio.run(check())
