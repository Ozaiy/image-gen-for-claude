/** Starts the MCP server on stdio. Used by both `npx` and the Claude Desktop extension (.mcpb). */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { generateImage, TOOL_DESCRIPTION, VERSION } from "./lib.js";

const server = new McpServer({ name: "openai-image", version: VERSION });

server.registerTool(
  "generate_image",
  {
    description: TOOL_DESCRIPTION,
    inputSchema: {
      prompt: z.string(),
      quality: z.enum(["low", "medium", "high"]).default("low"),
      size: z.enum(["1024x1024", "1536x1024", "1024x1536"]).default("1024x1024"),
      background: z.enum(["auto", "opaque", "transparent"]).default("auto"),
      output_format: z.enum(["png", "jpeg", "webp"]).default("png"),
      output_path: z.string().optional(),
      model: z.string().optional(),
    },
  },
  async (args) => {
    const [text, isError] = await generateImage(args);
    return { content: [{ type: "text", text }], isError };
  }
);

await server.connect(new StdioServerTransport());
