from fastapi.responses import JSONResponse


STATUS_TO_ERROR_TYPE = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    422: "invalid_request_error",
    429: "rate_limit_error",
}


def map_status_to_error_type(status_code: int) -> str:
    if status_code >= 500:
        return "api_error"
    return STATUS_TO_ERROR_TYPE.get(status_code, "api_error")


def to_anthropic_error(status_code: int, message: str) -> JSONResponse:
    error_type = map_status_to_error_type(status_code)
    return JSONResponse(
        status_code=status_code,
        content={
            "type": "error",
            "error": {
                "type": error_type,
                "message": message,
            },
        },
    )


def convert_error(status_code: int, openai_error: dict | None = None, message: str | None = None) -> dict:
    if openai_error and isinstance(openai_error, dict):
        err = openai_error.get("error", openai_error)
        msg = err.get("message", str(openai_error)) if isinstance(err, dict) else str(openai_error)
    elif message:
        msg = message
    else:
        msg = "Unknown backend error"
    error_type = map_status_to_error_type(status_code)
    return {
        "type": "error",
        "error": {
            "type": error_type,
            "message": msg,
        },
    }


def convert_openai_error(status_code: int, body: dict | str | None) -> JSONResponse:
    if isinstance(body, dict):
        err = body.get("error", {})
        message = err.get("message", str(body)) if isinstance(err, dict) else str(body)
    elif isinstance(body, str):
        message = body
    else:
        message = "Unknown backend error"
    return to_anthropic_error(status_code, message)


def format_stream_error(message: str) -> str:
    import json
    return json.dumps({
        "type": "error",
        "error": {
            "type": "api_error",
            "message": message,
        },
    })


def format_streaming_error(message: str, error_type: str = "api_error") -> dict:
    return {
        "event": "error",
        "data": {
            "type": "error",
            "error": {
                "type": error_type,
                "message": message,
            },
        },
    }
