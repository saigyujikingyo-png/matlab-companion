"""Six-tool MCP interface with server-side input, output and dispatch validation."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Annotated, Literal
from urllib.parse import urlparse

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from pydantic import Field, ValidationError

from . import __version__
from .contracts import (
    MAX_INLINE_BYTES,
    TOOL_OUTPUT_MODELS,
    ContractModel,
    Identifier,
    JobId,
    Operation,
    validate_dispatch_output,
)
from .core import Core, WorkflowError


class StatusInput(ContractModel):
    pass


class HelpInput(ContractModel):
    operation: Operation | None = None


class InspectInput(ContractModel):
    path: Annotated[str, Field(min_length=1, max_length=4096)]


class RunInput(ContractModel):
    operation: Operation
    parameters: Annotated[dict, Field(max_length=20)]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=128)]
    input_id: Identifier | None = None
    source_job_id: JobId | None = Field(
        default=None, description="Completed job UUID that owns the source figure."
    )
    source_artifact_id: Identifier | None = Field(
        default=None, description="native_figure artifact_id from that job's artifact list."
    )
    expected_revision: JobId | None = Field(
        default=None,
        description="Set to exactly source_job_id: immutable figure revisions are identified by their producing job UUID. This is not the artifact ID or SHA-256.",
    )


class JobInput(ContractModel):
    job_id: JobId
    action: Literal["status", "cancel", "reconcile"] = "status"


class ArtifactsInput(ContractModel):
    job_id: JobId | None = None
    action: Literal["list", "read", "deliver", "read_result", "read_schema"] = "list"
    artifact_id: Identifier | None = None
    destination: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=4096,
                description="Full destination FILE path including the artifact filename, under a setup-approved output folder; for example <output folder>/figure.fig.",
            ),
        ]
        | None
    ) = None
    operation: Operation | None = None
    schema_kind: Literal["parameters", "result"] = "parameters"


INPUT_MODELS = {
    "matlab_status": StatusInput,
    "matlab_help": HelpInput,
    "matlab_inspect": InspectInput,
    "matlab_run": RunInput,
    "matlab_job": JobInput,
    "matlab_artifacts": ArtifactsInput,
}
TOOL_DESCRIPTIONS = {
    "matlab_status": "Observe setup and native-version evidence without starting MATLAB.",
    "matlab_help": "Discover scientific operations and retrieve their parameter/result schemas on demand.",
    "matlab_inspect": "Register a user-selected CSV/TSV inside setup-approved folders; returns an input ID and original hash.",
    "matlab_run": "Queue an operation using help's parameter schema. Reuse an idempotency key for retries. For figure revisions provide source_job_id, source_artifact_id and expected_revision=source_job_id (the producing job UUID).",
    "matlab_job": "Read status, request cooperative cancellation or reconcile the existing native receipt. Cancellation requested is not stopped. Never replay an unknown write.",
    "matlab_artifacts": "List/read original files, retrieve schemas/results, or deliver with hash readback. Files above 16 MiB require action=deliver; their artifact URI identifies the original but cannot transfer its bytes. For deliver, destination is the full file path INCLUDING filename, not just a folder. MCP availability does not prove host receipt.",
}


def resource_content(core: Core, uri: str):
    parsed = urlparse(uri)
    if parsed.scheme != "matlab-companion" or parsed.query or parsed.fragment:
        raise WorkflowError("INPUT_INVALID", "Unknown resource URI")
    pieces = [part for part in parsed.path.split("/") if part]
    if parsed.netloc == "schemas" and len(pieces) == 2:
        return types.TextResourceContents(
            uri=uri,
            mimeType="application/schema+json",
            text=json.dumps(core.schema(*pieces), ensure_ascii=False, allow_nan=False),
        )
    if parsed.netloc == "results" and len(pieces) == 1:
        return types.TextResourceContents(
            uri=uri,
            mimeType="application/json",
            text=json.dumps(core.result(pieces[0]), ensure_ascii=False, allow_nan=False),
        )
    if parsed.netloc == "artifacts" and len(pieces) == 2:
        record, path = core.artifact_path(*pieces)
        if record["size_bytes"] > MAX_INLINE_BYTES:
            raise WorkflowError(
                "INPUT_INVALID",
                "File exceeds the inline transfer limit; use authorised local delivery",
            )
        return types.BlobResourceContents(
            uri=uri,
            mimeType=record["media_type"],
            blob=base64.b64encode(path.read_bytes()).decode("ascii"),
        )
    raise WorkflowError("INPUT_INVALID", "Unknown resource URI")


def create_server(core: Core) -> Server:
    async def list_tools(ctx, params):
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=name,
                    description=TOOL_DESCRIPTIONS[name],
                    inputSchema=INPUT_MODELS[name].model_json_schema(),
                    outputSchema=model.model_json_schema(),
                    annotations=types.ToolAnnotations(
                        readOnlyHint=name in {"matlab_status", "matlab_help"},
                        destructiveHint=False,
                        openWorldHint=False,
                    ),
                )
                for name, model in TOOL_OUTPUT_MODELS.items()
            ]
        )

    async def call_tool(ctx, params):
        name = params.name
        if name not in INPUT_MODELS:
            raise ValueError("Unknown tool")
        try:
            args = INPUT_MODELS[name].model_validate(params.arguments or {}).model_dump(mode="json")
            output = await asyncio.to_thread(core.call, name, args)
            if name in {"matlab_job", "matlab_artifacts"}:
                output = validate_dispatch_output(name, args["action"], output).model_dump(
                    mode="json"
                )
            content = []
            if output["ok"] and name == "matlab_artifacts":
                action = args["action"]
                uri = None
                if action == "read":
                    record = output["artifacts"][0]
                    if record["size_bytes"] <= MAX_INLINE_BYTES:
                        uri = record["uri"]
                elif action == "read_result":
                    uri = f"matlab-companion://results/{args['job_id']}"
                elif action == "read_schema":
                    uri = f"matlab-companion://schemas/{args['operation']}/{args['schema_kind']}"
                if uri:
                    resource = resource_content(core, uri)
                    if (
                        isinstance(resource, types.BlobResourceContents)
                        and resource.mime_type == "image/png"
                    ):
                        content.append(types.ImageContent(data=resource.blob, mimeType="image/png"))
                    else:
                        content.append(types.EmbeddedResource(resource=resource))
        except (ValueError, ValidationError, WorkflowError, OSError):
            job_id = params.arguments.get("job_id") if isinstance(params.arguments, dict) else None
            base = core._base(name, False)
            # Retain a valid known job even when payload or attachment construction fails.
            if job_id:
                try:
                    core._state(job_id)
                    base["job_id"] = job_id
                except (ValueError, WorkflowError):
                    pass
            base["error"] = {
                "code": "INPUT_OR_OUTPUT_INVALID",
                "message": "Request or result validation failed; inspect an existing job before retrying a write.",
            }
            output = TOOL_OUTPUT_MODELS[name].model_validate(base).model_dump(mode="json")
            content = []
        # Canonical metadata fallback accompanies matching structuredContent on every branch.
        content.insert(
            0, types.TextContent(text=json.dumps(output, ensure_ascii=False, allow_nan=False))
        )
        return types.CallToolResult(
            content=content, structuredContent=output, isError=not output["ok"]
        )

    async def list_resources(ctx, params):
        resources = []
        for operation in core._help()["operations"]:
            for kind in ("parameter", "result"):
                uri = operation[f"{kind}_schema_uri"]
                resources.append(
                    types.Resource(
                        name=f"{operation['operation']} {kind} schema",
                        uri=uri,
                        mimeType="application/schema+json",
                    )
                )
        return types.ListResourcesResult(resources=resources)

    async def read_resource(ctx, params):
        return types.ReadResourceResult(contents=[resource_content(core, str(params.uri))])

    return Server(
        "MATLAB Companion",
        version=__version__,
        instructions="Use matlab_help and read_schema to discover operation parameters. Inspect selected inputs, run with explicit units and idempotency keys, poll the returned job, then deliver original files. No arbitrary MATLAB evaluator is exposed. Native execution and received files are separate evidence.",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_list_resources=list_resources,
        on_read_resource=read_resource,
    )


async def serve(core: Core):
    server = create_server(core)
    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        core.close()
