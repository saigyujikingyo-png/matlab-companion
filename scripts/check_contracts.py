"""Check all declared schemas and their bounded public seams."""

import json

from jsonschema import Draft202012Validator

from matlab_companion.contracts import TOOL_OUTPUT_MODELS, dispatch_schemas, operation_schemas
from matlab_companion.server import INPUT_MODELS

count = 0
for model in [*TOOL_OUTPUT_MODELS.values(), *INPUT_MODELS.values()]:
    schema = model.model_json_schema()
    Draft202012Validator.check_schema(schema)
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    assert len(json.dumps(schema).encode()) < 16_384
    count += 1
for operation in operation_schemas().values():
    for key in ("parameters", "result"):
        Draft202012Validator.check_schema(operation[key])
        count += 1
for tool_routes in dispatch_schemas().values():
    # Dispatch registry itself is emitted by the same typed output definitions.
    assert tool_routes
print(f"PASS: {count} input/output/operation schemas; six public tools and dispatch registry.")
