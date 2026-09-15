"""Real file/handler/stdio transport tests; fixtures do not claim native validity."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sys
import uuid

import pytest
from jsonschema import Draft202012Validator
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

from matlab_companion.core import Core, WorkflowError
from matlab_companion.server import create_server
from matlab_companion.storage import atomic_json

TRANSFER_LIMIT = 16 * 1024 * 1024


class NoNativeBackend:
    def available(self):
        return False

    async def execute(self, job):
        raise AssertionError("Transport fixtures must never dispatch native work")


def stored_artifact(tmp_path, size, *, png=False):
    """Seed an already completed transport fixture without executing MATLAB."""
    root = tmp_path / "store"
    destination = tmp_path / "approved output"
    job_id = str(uuid.uuid4())
    job = root / "jobs" / job_id
    outputs = job / "outputs"
    outputs.mkdir(parents=True)
    name = "preview.png" if png else "transport-fixture.bin"
    path = outputs / name
    if png:
        payload = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII="
        )
    else:
        payload = bytes(range(256)) * (size // 256) + bytes(range(size % 256))
    path.write_bytes(payload)
    record = {
        "artifact_id": "transport-fixture",
        "job_id": job_id,
        "name": name,
        "role": "preview" if png else "native_data",
        "media_type": "image/png" if png else "application/octet-stream",
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "uri": f"matlab-companion://artifacts/{job_id}/transport-fixture",
        "verified": True,
    }
    atomic_json(
        job / "state.json",
        {
            "job_id": job_id,
            "operation": "data_profile",
            "state": "completed",
            "summary": "Portable transport fixture; no MATLAB execution.",
            "artifact_count": 1,
        },
    )
    atomic_json(job / "artifacts.json", {"artifacts": [record]})
    atomic_json(root / "settings.json", {"output_roots": [str(destination)]})
    return root, destination / name, record, payload


async def call_handler(server, method, arguments):
    entry = server.get_request_handler(method)
    assert entry is not None
    return await entry.handler(None, entry.params_type.model_validate(arguments))


async def artifact_call(server, record, action="read", **arguments):
    return await call_handler(
        server,
        "tools/call",
        {
            "name": "matlab_artifacts",
            "arguments": {
                "job_id": record["job_id"],
                "artifact_id": record["artifact_id"],
                "action": action,
                **arguments,
            },
        },
    )


def assert_metadata(result, record, schema):
    assert not result.is_error, result.structured_content
    output = result.structured_content
    Draft202012Validator(schema).validate(output)
    assert json.loads(result.content[0].text) == output
    assert output["job_id"] == record["job_id"]
    assert output["artifacts"] == [record]
    return output


@pytest.mark.parametrize("size", [TRANSFER_LIMIT - 1, TRANSFER_LIMIT, TRANSFER_LIMIT + 1])
def test_read_limit_routes_to_bytes_or_deliverable_metadata(tmp_path, size):
    root, target, record, payload = stored_artifact(tmp_path, size)
    core = Core(root, output_roots=[target.parent], backend=NoNativeBackend())

    async def check():
        server = create_server(core)
        listing = await call_handler(server, "tools/list", {})
        assert len(listing.tools) == 6
        schema = next(t.output_schema for t in listing.tools if t.name == "matlab_artifacts")
        result = await artifact_call(server, record)
        output = assert_metadata(result, record, schema)
        if size <= TRANSFER_LIMIT:
            assert output["delivery"]["state"] == "available"
            assert output["delivery"]["method"] == "mcp_resource"
            assert isinstance(result.content[1], types.EmbeddedResource)
            assert base64.b64decode(result.content[1].resource.blob) == payload
            resource = await call_handler(server, "resources/read", {"uri": record["uri"]})
            assert base64.b64decode(resource.contents[0].blob) == payload
        else:
            assert [item.type for item in result.content] == ["text"]
            assert len(result.content[0].text) < 4096
            receipt = output["delivery"]
            assert receipt["state"] == "not_delivered"
            assert receipt["method"] == "local_copy"
            assert receipt["size_bytes"] == size
            assert receipt["sha256"] == record["sha256"]
            assert receipt["destination"] is None
            assert "deliver" in receipt["reason"] and "filename" in receipt["reason"]
            with pytest.raises(WorkflowError, match="local delivery"):
                await call_handler(server, "resources/read", {"uri": record["uri"]})
        assert not target.exists()
        rejected = await artifact_call(
            server, record, "deliver", destination=str(tmp_path / "unapproved.bin")
        )
        assert rejected.is_error and not (tmp_path / "unapproved.bin").exists()
        delivered = await artifact_call(server, record, "deliver", destination=str(target))
        receipt = assert_metadata(delivered, record, schema)["delivery"]
        assert receipt["state"] == "verified" and receipt["method"] == "local_copy"
        assert receipt["size_bytes"] == len(payload)
        assert receipt["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
        assert target.read_bytes() == payload

    try:
        asyncio.run(check())
    finally:
        core.close()


def test_small_png_read_preserves_image_content_and_json_fallback(tmp_path):
    root, target, record, payload = stored_artifact(tmp_path, 0, png=True)
    core = Core(root, output_roots=[target.parent], backend=NoNativeBackend())

    async def check():
        result = await artifact_call(create_server(core), record)
        assert not result.is_error
        assert json.loads(result.content[0].text) == result.structured_content
        assert isinstance(result.content[1], types.ImageContent)
        assert result.content[1].mime_type == "image/png"
        assert base64.b64decode(result.content[1].data) == payload

    try:
        asyncio.run(check())
    finally:
        core.close()


def test_handler_rejects_misleading_over_limit_metadata_and_keeps_job(tmp_path, monkeypatch):
    root, target, record, _ = stored_artifact(tmp_path, TRANSFER_LIMIT + 1)
    core = Core(root, output_roots=[target.parent], backend=NoNativeBackend())
    actual_call = core.call

    def invalid_producer(name, arguments):
        output = actual_call(name, arguments)
        output["delivery"] = {
            "artifact_id": record["artifact_id"],
            "state": "available",
            "method": "mcp_resource",
        }
        return output

    monkeypatch.setattr(core, "call", invalid_producer)

    async def check():
        result = await artifact_call(create_server(core), record)
        assert result.is_error
        assert result.structured_content["job_id"] == record["job_id"]
        assert result.structured_content["error"]["code"] == "INPUT_OR_OUTPUT_INVALID"
        assert [item.type for item in result.content] == ["text"]
        assert json.loads(result.content[0].text) == result.structured_content
        assert not target.exists()

    try:
        asyncio.run(check())
    finally:
        core.close()


def test_oversized_artifact_can_be_delivered_through_real_stdio(tmp_path):
    root, target, record, payload = stored_artifact(tmp_path, TRANSFER_LIMIT + 1)

    async def check():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "matlab_companion", "serve", "--root", str(root)],
        )
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            listing = await session.list_tools()
            schema = next(t.output_schema for t in listing.tools if t.name == "matlab_artifacts")
            args = {"job_id": record["job_id"], "artifact_id": record["artifact_id"]}
            result = await session.call_tool("matlab_artifacts", args | {"action": "read"})
            output = assert_metadata(result, record, schema)
            assert len(result.content) == 1
            assert output["delivery"]["method"] == "local_copy"
            assert output["delivery"]["state"] == "not_delivered"
            delivered = await session.call_tool(
                "matlab_artifacts", args | {"action": "deliver", "destination": str(target)}
            )
            receipt = assert_metadata(delivered, record, schema)["delivery"]
            assert receipt["state"] == "verified"
            assert receipt["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
            assert target.read_bytes() == payload

    asyncio.run(check())
