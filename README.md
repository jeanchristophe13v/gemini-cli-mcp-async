# Gemini CLI MCP Server

Async wrapper for Gemini CLI to enable parallel task execution in Claude Code.

## Features

- **Async execution** - Run tasks in background without blocking
- **Multi-instance** - Execute multiple Gemini CLI tasks in parallel
- **Zombie process cleanup** - Automatic cleanup of finished processes
- **Zero configuration** - Works out of the box

## Quick Start

### 1. Install

```bash
git clone https://github.com/your-username/gemini-cli-mcp-async.git
cd gemini-cli-mcp-async
chmod +x gemini_cli_mcp_async_server.py
```

### 2. Configure Claude Code

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "gemini-cli": {
      "command": "python3",
      "args": ["/absolute/path/to/gemini-cli-mcp-async/gemini_cli_mcp_async_server.py"],
      "env": {}
    }
  }
}
```

### 3. Restart Claude Code

## Usage

### Async execution

```python
# Start async task
gemini_cli_execute_async(
    query="your prompt here",
    working_dir="/path/to/project"
)
# Returns: task_id

# Check result
gemini_cli_check_result(task_id="your_task_id")
```

### Parallel execution

```python
# Start multiple tasks
task1 = gemini_cli_execute_async(query="task 1", yolo=True)
task2 = gemini_cli_execute_async(query="task 2", sandbox=True)

# Check results later
result1 = gemini_cli_check_result(task_id=task1)
result2 = gemini_cli_check_result(task_id=task2)
```

### Sync execution

```python
# Immediate result
gemini_cli_execute(
    query="your prompt here",
    timeout=300
)
```

## API Reference

### gemini_cli_execute(query, working_dir, sandbox, yolo, approval_mode, experimental_acp, allowed_mcp_server_names, allowed_tools, extensions, include_directories, output_format, screen_reader, debug, additional_args, timeout)

Execute Gemini CLI synchronously and return result immediately.

### gemini_cli_execute_async(query, working_dir, sandbox, yolo, approval_mode, experimental_acp, allowed_mcp_server_names, allowed_tools, extensions, include_directories, output_format, screen_reader, debug, additional_args)

Start Gemini CLI task in background and return task_id.

### gemini_cli_check_result(task_id)

Check status of async task and return result if completed.

## Troubleshooting

**Server not showing in Claude Code:**
- Check file path is absolute and correct
- Ensure file has execute permissions (`chmod +x`)
- Verify gemini-cli is installed and accessible

**Tasks stuck:**
- Check task status with `gemini_cli_check_result()`
- View debug log: `tail -f /tmp/gemini_cli_mcp_debug.log`

**No output from long tasks:**
- Use `output_format="stream-json"` for better output capture
- Check disk space in `/tmp`

## Configuration

All Gemini CLI parameters are supported. Key options:

- `sandbox` - Enable sandbox mode
- `yolo` - Auto-confirm prompts
- `approval_mode` - Set approval mode ('default', 'auto_edit', 'yolo')
- `output_format` - Output format ('text', 'json', 'stream-json')
- `timeout` - Timeout for sync execution (seconds)
- `debug` - Enable debug logging
