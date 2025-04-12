import asyncio
import hashlib
import logging
import traceback
import mcp
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Set, Optional, List

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.stdio import stdio_server
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Enable debug logging for MCP
logging.getLogger('mcp').setLevel(logging.DEBUG)

@dataclass
class Subscription:
    url: str
    client_id: str
    last_content_hash: str
    last_check: datetime
    check_interval: timedelta = timedelta(minutes=5)

class SubscribeMCPProxy:
    def __init__(self, base_server_command: list[str]):
        print("Initializing proxy")
        self.server = Server("Subscribe MCP Proxy")
        self.base_client = None
        self.base_server_command = base_server_command
        
        # Track active subscriptions
        self.subscriptions: Dict[str, Set[Subscription]] = {}
        

    async def start(self):
        # Connect to base server 
        logger.info(f"Connecting to base server with command: {self.base_server_command}")
        server_params = StdioServerParameters(
            command=self.base_server_command[0],
            args=self.base_server_command[1:],
            env={"PYTHONUNBUFFERED": "1"}
        )
        
        async with stdio_client(server_params) as (base_read, base_write):
            async with ClientSession(base_read, base_write) as session:
                self.base_client = session
                
                # Initialize the connection to base server and store capabilities
                init_result = await session.initialize()
                server_capabilities = init_result.capabilities
                
                # Set up request handlers based on server capabilities
                if server_capabilities.tools:
                    self.server.request_handlers[mcp.types.CallToolRequest] = self.handle_tool_call
                    self.server.request_handlers[mcp.types.ListToolsRequest] = self.handle_list_tools
                
                if server_capabilities.resources:
                    self.server.request_handlers[mcp.types.ReadResourceRequest] = self.handle_resource_get
                    self.server.request_handlers[mcp.types.ListResourcesRequest] = self.handle_list_resources
                
                if server_capabilities.prompts:
                    self.server.request_handlers[mcp.types.ListPromptsRequest] = self.handle_list_prompts
                    self.server.request_handlers[mcp.types.GetPromptRequest] = self.handle_get_prompt

                # Handle client connections through stdin/stdout
                async with stdio_server() as (client_read, client_write):
                    await self.server.run(
                        client_read,
                        client_write,
                        InitializationOptions(
                            server_name="subscribe-mcp-proxy",
                            server_version="0.1.0",
                            capabilities=self.server.get_capabilities(
                                notification_options=NotificationOptions(),
                                experimental_capabilities={}
                            ),
                        ),
                    )
                async with stdio_server(self.server):
                    # Keep running until interrupted
                    while True:
                        await asyncio.sleep(1)



    async def handle_tool_call(self, req: mcp.types.CallToolRequest) -> mcp.types.CallToolResult:
        """Forward tool calls to the base server."""
        try:
            result = await self.base_client.call_tool(req.params.name, req.params.arguments)
            return mcp.types.CallToolResult(
                content=result.content,
                isError=False
            )
        except Exception as e:
            return mcp.types.CallToolResult(
                content=[mcp.types.TextContent(type="text", text=str(e))],
                isError=True
            )

    async def handle_resource_get(self, req: mcp.types.ReadResourceRequest) -> mcp.types.ReadResourceResult:
        """Forward resource requests to the base server."""
        try:
            # Assume the base_client.get_resource returns a string (or bytes) representing the resource.
            resource_data = await self.base_client.get_resource(req.params.uri)
        except Exception as e:
            # If an error occurs, you might wish to raise or build an error result.
            return mcp.types.ReadResourceResult(
                contents=[
                    mcp.types.TextResourceContents(
                        uri=req.params.uri,
                        text=f"Error: {e}",
                        mimeType="text/plain"
                    )
                ]
            )

        # For this example, assume resource_data is a string.
        content = mcp.types.TextResourceContents(
            uri=req.params.uri,
            text=resource_data,
            mimeType="text/plain"
        )
        return mcp.types.ReadResourceResult(contents=[content])

    async def handle_list_tools(self, req: mcp.types.ListToolsRequest) -> mcp.types.ListToolsResult:
        """Forward tool listing request to the base server."""
        result = await self.base_client.list_tools()
        # Create a new ListToolsResult with the tools from the base server
        return mcp.types.ListToolsResult(tools=result.tools)

    async def handle_list_resources(self, req: mcp.types.ListResourcesRequest) -> mcp.types.ListResourcesResult:
        """Forward resource listing request to the base server."""
        resources = await self.base_client.list_resources()
        return mcp.types.ListResourcesResult(resources=resources)

    async def handle_list_prompts(self, req: mcp.types.ListPromptsRequest) -> mcp.types.ListPromptsResult:
        """Forward prompt listing request to the base server."""
        result = await self.base_client.list_prompts()
        return mcp.types.ListPromptsResult(prompts=result.prompts)

    async def handle_get_prompt(self, req: mcp.types.GetPromptRequest) -> mcp.types.GetPromptResult:
        """Forward prompt request to the base server."""
        try:
            prompt_result = await self.base_client.get_prompt(req.params.name, req.params.arguments)
            return prompt_result
        except Exception as e:
            logger.error(f"Error getting prompt: {e}")
            return mcp.types.GetPromptResult(
                description=f"Error getting prompt: {e}",
                messages=[]
            )

    async def add_subscription(self, url: str, client_id: str):
        """Add a subscription for a client"""
        try:
            # Get initial content
            result = await self.base_client.call_tool("fetch", {"url": url})
            content = result.result
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            
            # Create subscription
            sub = Subscription(
                url=url,
                client_id=client_id,
                last_content_hash=content_hash,
                last_check=datetime.now()
            )
            
            # Add to subscriptions
            if url not in self.subscriptions:
                self.subscriptions[url] = set()
            
            # Remove existing subscription if any
            self.subscriptions[url] = {s for s in self.subscriptions[url] if s.client_id != client_id}
            # Add new subscription
            self.subscriptions[url].add(sub)
            
            return True
        except Exception as e:
            logger.error(f"Error adding subscription: {e}")
            return False


async def main():
    # Example usage
    logging.info("Creating proxy")
    proxy = SubscribeMCPProxy(["uvx", "mcp-server-fetch"])
    logging.info("Proxy created")
    try:
        logging.info("Starting proxy")
        await proxy.start()
        logging.info("Proxy started")
    except Exception as e:
        logging.error(f"Error starting proxy: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())