/** Starts the MCP server on stdio. Used by both `npx` and the Claude Desktop extension (.mcpb). */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { generateImage, TOOL_DESCRIPTION, VERSION } from "./lib.js";
// The same view the Python server uses; esbuild bundles it as a string
import VIEW_HTML from "../../src/openai_image_mcp/view.html";

// MCP Apps: hosts that support it (Claude Desktop, claude.ai) show the image large,
// inline in the chat, using this HTML view. Other clients ignore it.
const VIEW_URI = "ui://openai-image/view.html";
const VIEW_MIME_TYPE = "text/html;profile=mcp-app";

const server = new McpServer({ name: "openai-image", version: VERSION });

server.registerResource(
  "image_view",
  VIEW_URI,
  { title: "Generated image", mimeType: VIEW_MIME_TYPE, _meta: { ui: { prefersBorder: false } } },
  async () => ({
    contents: [{ uri: VIEW_URI, mimeType: VIEW_MIME_TYPE, text: VIEW_HTML, _meta: { ui: { prefersBorder: false } } }],
  })
);

server.registerTool(
  "generate_image",
  {
    description: TOOL_DESCRIPTION,
    // "ui/resourceUri" is the older spelling of the same key, for hosts that only know that one
    _meta: { ui: { resourceUri: VIEW_URI }, "ui/resourceUri": VIEW_URI },
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
    const [text, isError, preview] = await generateImage(args);
    const content: ({ type: "text"; text: string } | { type: "image"; data: string; mimeType: string })[] = [
      { type: "text", text },
    ];
    if (preview) content.push({ type: "image", data: preview.data, mimeType: preview.mimeType });
    return { content, isError };
  }
);

await server.connect(new StdioServerTransport());
