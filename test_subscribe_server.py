import asyncio
import traceback
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

async def test_subscription():
    # Create server parameters for stdio connection
    server_params = StdioServerParameters(
        command="python",  # Executable
        args=["subscribe_mcp_proxy.py"],  # Command line arguments
        env=None,  # Optional environment variables
    )
    
    # Handler for notifications
    async def handle_notification(notification: types.Notification):
        print(f"Received notification: {notification.type}")
        print(f"Changed resource:", notification.data)
    
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
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

                #test_url = "https://news.ycombinator.com"
                #await session.subscribe_resource(
                #    "webpage",  # resource template name
                #    {"url": test_url}  # parameters
                #)

                #print(f"Subscribed to webpage resource with URL: {test_url}")
                #print("Waiting for notifications. Press Ctrl+C to stop...")

    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_subscription())
