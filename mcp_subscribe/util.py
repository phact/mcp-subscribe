from urllib.parse import parse_qs


async def call_tool_from_uri(uri, session):
    if uri.scheme == "tool":
        args = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(uri.query).items()}
        name = uri.host
        tool_result = await session.call_tool(name, args)
        return tool_result

