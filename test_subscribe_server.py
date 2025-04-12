import asyncio
import traceback
from urllib.parse import parse_qs

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

from util import call_tool_from_uri


async def test_subscription():
    # Create server parameters for stdio connection
    server_params = StdioServerParameters(
        command="python",  # Executable
        args=["subscribe_mcp_proxy.py"],  # Command line arguments
        env=None,  # Optional environment variables
    )

    messages = []
    
    # Handler for notifications
    async def handle_notification(message):
        messages.append(message)



    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write, message_handler=handle_notification) as session:
                # Initialize the connection
                init_result = await session.initialize()
                capabilities = init_result.capabilities

                if capabilities.tools:
                    result = await session.list_tools()
                    print("Available tools:", [t.name for t in result.tools])

                    result = await session.call_tool(result.tools[0].name, {"url": "https://news.ycombinator.com"})
                    print("Result:", result)

                if capabilities.resources:
                    result = await session.list_resources()
                    print("Available resources:", [r.name for r in result.resources])

                    # List available resources
                    result = await session.list_resources()
                    print("Available resources:", [r.name for r in result.resources])

                if capabilities.prompts:
                    result = await session.list_prompts()
                    print("Available prompts:", [p.name for p in result.prompts])

                    result = await session.get_prompt(result.prompts[0].name, {"url": "https://news.ycombinator.com"})
                    print("Prompt:", result)

                #result = await session.subscribe_resource("tool://fetch/?url=https://news.ycombinator.com")
                result = await session.subscribe_resource("tool://fetch/?url=http://localhost:8000/test")
                print("Subscribed to resource:", result)

                while True:
                    await asyncio.sleep(1)
                    for message in messages:
                        uri = message.root.params.uri
                        result = await call_tool_from_uri(uri, session)
                        print(result)
                        messages.remove(message)


    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()



if __name__ == "__main__":
    asyncio.run(test_subscription())
