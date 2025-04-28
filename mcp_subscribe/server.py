import asyncio
import hashlib

from pydantic.networks import AnyUrl
import logging
import traceback
import mcp
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict
import argparse

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.stdio import stdio_server
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions

from mcp_subscribe.util import call_tool_from_uri

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Enable debug logging for MCP
logging.getLogger('mcp').setLevel(logging.DEBUG)

@dataclass
class Subscription:
    url: AnyUrl
    last_content_hash: str
    last_check: datetime
    check_interval: timedelta = timedelta(seconds=1)

class SubscribeMCPProxy:
    def __init__(self, base_server_command: list[str], poll_interval: float = 1.0):
        """
        :param base_server_command: list of command and args to launch the base MCP server
        :param poll_interval: seconds to sleep between subscription check loops
        """
        print("Initializing proxy")
        self.server = Server("Subscribe MCP Proxy")
        self.session = None
        self.base_client = None
        self.base_server_command = base_server_command
        # Loop delay for subscription polling
        self.poll_interval = poll_interval
        # Track active subscriptions
        self.subscriptions: Dict[AnyUrl, Subscription] = {}
        

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
                self.server_capabilities = init_result.capabilities
                
                # Set up request handlers based on server capabilities
                if self.server_capabilities.tools:
                    self.server.request_handlers[mcp.types.CallToolRequest] = self.handle_tool_call
                    self.server.request_handlers[mcp.types.ListToolsRequest] = self.handle_list_tools
                
                if self.server_capabilities.resources:
                    self.server.request_handlers[mcp.types.ReadResourceRequest] = self.handle_resource_get
                    self.server.request_handlers[mcp.types.ListResourcesRequest] = self.handle_list_resources

                self.server.request_handlers[mcp.types.SubscribeRequest] = self.handle_subscribe
                self.server.request_handlers[mcp.types.UnsubscribeRequest] = self.handle_unsubscribe
                
                if self.server_capabilities.prompts:
                    self.server.request_handlers[mcp.types.ListPromptsRequest] = self.handle_list_prompts
                    self.server.request_handlers[mcp.types.GetPromptRequest] = self.handle_get_prompt

                # Add logging handler
                self.server.request_handlers[mcp.types.SetLevelRequest] = self.handle_set_level

                server = self.server


                # Handle client connections through stdin/stdout
                async with stdio_server() as (client_read, client_write):
                    # Start background task for subscription checks
                    check_task = asyncio.create_task(self.check_subscriptions())
                    
                    try:
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
                    finally:
                        check_task.cancel()
                        try:
                            await check_task
                        except asyncio.CancelledError:
                            pass

    async def check_subscriptions(self):
        """Background task to check subscriptions"""
        while True:
            # sleep for configured poll interval
            await asyncio.sleep(self.poll_interval)
            for url, sub in self.subscriptions.items():
                if sub.last_check + sub.check_interval < datetime.now():
                    # Check for updates
                    result =  await call_tool_from_uri(sub.url, self.base_client)
                    new_hash = hashlib.md5(result.content[0].text.encode()).hexdigest()
                    if new_hash != sub.last_content_hash:
                        sub.last_content_hash = hashlib.md5(result.content[0].text.encode()).hexdigest()
                        sub.last_check = datetime.now()
                        self.server.list_resources()
                        if self.session:
                            await self.session.send_resource_updated(sub.url)

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

    async def handle_subscribe(self, req: mcp.types.SubscribeRequest) -> mcp.types.EmptyResult:
        """Forward subscription request to the base server."""
        if self.session is None:
            self.session = self.server.request_context.session

        if resources := getattr(self.server_capabilities, 'resources', None):
            if getattr(resources, 'subscribe', False):
                await self.base_client.subscribe_resource(req.params.uri)

        await self.add_subscription(req.params.uri)
        return mcp.types.EmptyResult()

    async def handle_unsubscribe(self, req: mcp.types.UnsubscribeRequest) -> mcp.types.EmptyResult:
        """Forward unsubscribe request to the base server."""
        if self.server_capabilities.resources.subscribe:
            await self.base_client.unsubscribe_resource(req.params.uri)
        del self.subscriptions[req.params.uri]
        return mcp.types.EmptyResult()

    async def add_subscription(self, url: AnyUrl):
        """Add a subscription for a client"""
        try:
            # Get initial content
            #result = await self.base_client.call_tool()
            #content = result.result
            #content_hash = hashlib.sha256(content.encode()).hexdigest()
            result =  await call_tool_from_uri(url, self.base_client)
            #TODO: do we need to support other content types / indices?
            content_hash = hashlib.md5(result.content[0].text.encode()).hexdigest()

            # Create subscription
            sub = Subscription(
                url=url,
                last_content_hash=content_hash,
                last_check=datetime.now()
            )
            
            # Add to subscriptions
            self.subscriptions[url] = sub

            return True
        except Exception as e:
            logger.error(f"Error adding subscription: {e}")
            return False

    async def handle_set_level(self, req: mcp.types.SetLevelRequest) -> mcp.types.EmptyResult:
        """Forward logging level changes to the base server."""
        # Forward the logging level to the base client
        await self.base_client.set_level(req.params.level)
        # Also set our own logging level
        logging.getLogger().setLevel(req.params.level.upper())
        return mcp.types.EmptyResult()


async def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Subscribe MCP Proxy")
    parser.add_argument(
        "--poll-interval", "-p",
        type=float,
        default=1.0,
        help="Polling interval in seconds for subscription checks",
    )
    parser.add_argument(
        "base_server_command",
        nargs='+',
        help="Base MCP server command and its arguments",
    )
    args = parser.parse_args()

    base_cmd = args.base_server_command
    poll_interval = args.poll_interval

    logging.info(f"Creating proxy: base_server_command={base_cmd}, poll_interval={poll_interval}s")
    proxy = SubscribeMCPProxy(base_cmd, poll_interval=poll_interval)
    logging.info("Proxy created")
    try:
        logging.info("Starting proxy")
        await proxy.start()
        logging.info("Proxy started")
    except Exception as e:
        logging.error(f"Error starting proxy: {e}")
        traceback.print_exc()


def app():
    asyncio.run(main())

if __name__ == "__main__":
    app()