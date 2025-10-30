# Gemini CLI MCP API Reference

## Tools

### gemini_cli_execute

Execute Gemini CLI synchronously with full parameter support.

**Parameters:**
- `query` (string|string[], optional) - Prompt or command arguments
- `working_dir` (string, optional) - Working directory (default: current)
- `sandbox` (boolean, default: false) - Enable sandbox mode
- `yolo` (boolean, default: false) - Auto-confirm prompts
- `approval_mode` ("default"|"auto_edit"|"yolo", optional) - Approval mode
- `experimental_acp` (boolean, default: false) - Enable experimental ACP
- `allowed_mcp_server_names` (string[], optional) - Whitelisted MCP servers
- `allowed_tools` (string[], optional) - Whitelisted tools
- `extensions` (string[], optional) - Gemini CLI extensions
- `include_directories` (string[], optional) - Additional directories
- `output_format` ("text"|"json"|"stream-json", optional) - Output format
- `screen_reader` (boolean, default: false) - Screen reader mode
- `debug` (boolean, default: false) - Debug logging
- `additional_args` (string[], optional) - Extra CLI arguments
- `timeout` (integer, optional) - Timeout in seconds

**Returns:** String result from Gemini CLI

### gemini_cli_execute_async

Start Gemini CLI task in background.

**Parameters:** Same as `gemini_cli_execute` except `timeout`

**Returns:** Task ID string for checking status

### gemini_cli_check_result

Check async task status and get result.

**Parameters:**
- `task_id` (string, required) - Task ID from async execution

**Returns:** Status object with:
- `status` ("running"|"completed"|"error"|"not_found")
- `task_id` - Task identifier
- `result` (if completed) - Task result
- `elapsed_seconds` - Time elapsed
- `working_dir` - Working directory
- `command` - Executed command
- `error` (if error) - Error message

## Response Format

All tools return content in format:
```json
{
  "content": [{"type": "text", "text": "result"}]
}
```