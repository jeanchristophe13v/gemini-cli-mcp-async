"""
Gemini CLI MCP Server Wrapper with Async Support
将 Gemini CLI 封装为符合 MCP 协议的 server，支持异步任务
"""
import sys
import json
import subprocess
import uuid
import os
import time
import logging
import signal
import traceback
import shlex
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

__all__ = ["main"]

# 配置日志系统
logging.basicConfig(
    filename='/tmp/gemini_cli_mcp_debug.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - [%(funcName)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logging.info("=== Gemini CLI MCP Server Starting ===")

# 任务存储目录
TASK_DIR = Path("/tmp/gemini_cli_tasks")
TASK_DIR.mkdir(exist_ok=True)


# ============================================
# 僵尸进程自动回收机制
# ============================================
def sigchld_handler(signum, frame):
    """
    SIGCHLD 信号处理器：自动回收已终止的子进程，防止僵尸进程累积
    """
    del signum, frame
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break

            exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
            logging.debug(f"Reaped child process PID {pid}, exit_code={exit_code}, status={status}")
        except ChildProcessError:
            break
        except Exception as exc:
            logging.warning(f"Error in SIGCHLD handler: {exc}")
            break


signal.signal(signal.SIGCHLD, sigchld_handler)
logging.info("SIGCHLD handler registered for automatic zombie process reaping")


def safe_read_file(file_path: Path) -> str:
    """安全地读取文件，处理各种编码和异常问题"""
    if not file_path.exists():
        logging.debug(f"File {file_path} does not exist")
        return ""

    try:
        content = file_path.read_text(encoding='utf-8')
        logging.debug(f"Successfully read {file_path} with UTF-8 encoding ({len(content)} chars)")
        return content
    except UnicodeDecodeError as exc:
        logging.warning(f"UTF-8 decode error for {file_path}: {exc}, using replace mode")
        try:
            content = file_path.read_text(encoding='utf-8', errors='replace')
            logging.debug(f"Read {file_path} with replace mode ({len(content)} chars)")
            return content
        except Exception as inner_exc:
            logging.error(f"Failed to read {file_path} even with replace mode: {inner_exc}")
            return f"[Error reading file: {inner_exc}]"
    except PermissionError as exc:
        logging.error(f"Permission denied reading {file_path}: {exc}")
        return f"[Permission denied: {exc}]"
    except Exception as exc:
        logging.error(f"Unexpected error reading {file_path}: {exc}")
        return f"[Unexpected error: {exc}]"


def is_process_alive(pid: Optional[int]) -> bool:
    """检测进程是否还在运行（排除僵尸进程）"""
    if pid is None:
        return False

    try:
        os.kill(pid, 0)
        try:
            result = subprocess.run(
                ['ps', '-p', str(pid), '-o', 'stat='],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=1
            )
            if result.returncode == 0:
                stat = result.stdout.strip()
                if stat.startswith('Z'):
                    logging.debug(f"PID {pid} is a zombie process")
                    return False
                return True
            return False
        except Exception as exc:
            logging.warning(f"Failed to check process state for PID {pid}: {exc}")
            return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception as exc:
        logging.warning(f"Unexpected error checking PID {pid}: {exc}")
        return False


def send_response(response: Dict[str, Any]) -> None:
    """发送JSON-RPC响应到stdout"""
    try:
        output = json.dumps(response, ensure_ascii=False)
        print(output, flush=True)
        logging.debug(f"Sent response: id={response.get('id')}, size={len(output)} bytes")
    except (TypeError, ValueError) as exc:
        logging.error(f"Failed to serialize response: {exc}, response={response}")
        error_response = {
            'jsonrpc': '2.0',
            'id': response.get('id'),
            'error': {
                'code': -32603,
                'message': f'Response serialization failed: {str(exc)}'
            }
        }
        print(json.dumps(error_response), flush=True)


def _extend_repeating_option(cmd: List[str], flag: str, values: Optional[Iterable[str]]) -> None:
    """为 CLI 添加可重复的数组参数"""
    if not values:
        return
    for value in values:
        if value is None:
            continue
        cmd.extend([flag, str(value)])


def _coerce_query_arguments(query: Optional[Union[str, Sequence[str]]]) -> List[str]:
    """规范化 query 参数为列表"""
    if query is None:
        return []
    if isinstance(query, str):
        return [query]
    result: List[str] = []
    for item in query:
        if item is None:
            continue
        result.append(str(item))
    return result


def build_gemini_command(
    query: Optional[Union[str, Sequence[str]]] = None,
    sandbox: bool = False,
    yolo: bool = False,
    approval_mode: Optional[str] = None,
    experimental_acp: bool = False,
    allowed_mcp_server_names: Optional[Sequence[str]] = None,
    allowed_tools: Optional[Sequence[str]] = None,
    extensions: Optional[Sequence[str]] = None,
    include_directories: Optional[Sequence[str]] = None,
    output_format: Optional[str] = None,
    screen_reader: bool = False,
    debug: bool = False,
    additional_args: Optional[Sequence[str]] = None
) -> List[str]:
    """根据参数构建 Gemini CLI 命令"""
    cmd: List[str] = ['gemini']
    if sandbox:
        cmd.append('--sandbox')
    if yolo:
        cmd.append('--yolo')
    if approval_mode:
        cmd.extend(['--approval-mode', approval_mode])
    if experimental_acp:
        cmd.append('--experimental-acp')

    _extend_repeating_option(cmd, '--allowed-mcp-server-names', allowed_mcp_server_names)
    _extend_repeating_option(cmd, '--allowed-tools', allowed_tools)
    _extend_repeating_option(cmd, '--extensions', extensions)
    _extend_repeating_option(cmd, '--include-directories', include_directories)

    if output_format:
        cmd.extend(['--output-format', output_format])
    if screen_reader:
        cmd.append('--screen-reader')
    if debug:
        cmd.append('--debug')

    if additional_args:
        cmd.extend(str(arg) for arg in additional_args if arg is not None)

    cmd.extend(_coerce_query_arguments(query))
    logging.debug("Constructed gemini command: %s", ' '.join(shlex.quote(part) for part in cmd))
    return cmd


def extract_result_from_gemini_output(stdout: str, stderr: str, output_format: Optional[str] = None) -> str:
    """从 Gemini CLI 输出中提取结果"""
    stdout = stdout or ""
    stderr = stderr or ""
    output_format = output_format or "text"

    logging.debug(
        "Extracting Gemini result: stdout_len=%d, stderr_len=%d, format=%s",
        len(stdout),
        len(stderr),
        output_format
    )

    if output_format == "json":
        try:
            data = json.loads(stdout.strip())
            formatted = json.dumps(data, indent=2, ensure_ascii=False)
            logging.debug("Extracted JSON result (%d chars)", len(formatted))
            return formatted
        except json.JSONDecodeError as exc:
            logging.warning(f"JSON decode failed: {exc}, falling back to text mode")

    if output_format == "stream-json":
        lines = [line for line in stdout.splitlines() if line.strip()]
        collected: List[str] = []
        for line in lines:
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    # 尝试提取常见字段
                    text = obj.get('text') or obj.get('content') or obj.get('result')
                    if isinstance(text, str):
                        collected.append(text)
                        continue
                collected.append(line)
            except json.JSONDecodeError:
                collected.append(line)
        if collected:
            result = "\n".join(collected).strip()
            logging.debug("Extracted stream-json result (%d chars)", len(result))
            return result

    text = stdout.strip()
    if text:
        return text

    if stderr.strip():
        return stderr.strip()

    logging.warning("No output from Gemini CLI (both stdout and stderr empty)")
    return "No output from Gemini CLI"


def start_gemini_async(
    query: Optional[Union[str, Sequence[str]]] = None,
    working_dir: Optional[str] = None,
    sandbox: bool = False,
    yolo: bool = False,
    approval_mode: Optional[str] = None,
    experimental_acp: bool = False,
    allowed_mcp_server_names: Optional[Sequence[str]] = None,
    allowed_tools: Optional[Sequence[str]] = None,
    extensions: Optional[Sequence[str]] = None,
    include_directories: Optional[Sequence[str]] = None,
    output_format: Optional[str] = None,
    screen_reader: bool = False,
    debug: bool = False,
    additional_args: Optional[Sequence[str]] = None
) -> str:
    """启动异步 Gemini CLI 任务"""
    additional_args = list(additional_args) if additional_args else []
    task_id = str(uuid.uuid4())[:8]
    task_path = TASK_DIR / task_id

    cmd = build_gemini_command(
        query=query,
        sandbox=sandbox,
        yolo=yolo,
        approval_mode=approval_mode,
        experimental_acp=experimental_acp,
        allowed_mcp_server_names=allowed_mcp_server_names,
        allowed_tools=allowed_tools,
        extensions=extensions,
        include_directories=include_directories,
        output_format=output_format,
        screen_reader=screen_reader,
        debug=debug,
        additional_args=additional_args
    )

    stdout_file = task_path.with_suffix('.stdout')
    stderr_file = task_path.with_suffix('.stderr')

    cwd = working_dir or os.getcwd()
    logging.info("Starting Gemini async task %s in %s", task_id, cwd)

    try:
        with open(stdout_file, 'w') as stdout_f, open(stderr_file, 'w') as stderr_f:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=stdout_f,
                stderr=stderr_f,
                text=True,
                cwd=cwd,
                start_new_session=True
            )

        metadata = {
            'task_id': task_id,
            'pid': proc.pid,
            'status': 'running',
            'command': ' '.join(shlex.quote(part) for part in cmd),
            'working_dir': cwd,
            'output_format': output_format or 'text',
            'started_at': time.time()
        }

        with open(task_path.with_suffix('.meta'), 'w', encoding='utf-8') as meta_file:
            json.dump(metadata, meta_file, indent=2)

        logging.debug(f"Task {task_id} metadata saved")
        return task_id

    except Exception as exc:
        logging.error(f"Failed to start async task {task_id}: {exc}\n{traceback.format_exc()}")
        raise


def check_task_status(task_id: str) -> Dict[str, Any]:
    """检查任务状态并返回结果"""
    logging.debug(f"Checking status for task {task_id}")
    task_path = TASK_DIR / task_id
    meta_file = task_path.with_suffix('.meta')

    if not meta_file.exists():
        logging.warning(f"Task {task_id} not found")
        return {
            'status': 'not_found',
            'error': f'Task {task_id} not found'
        }

    try:
        with open(meta_file, 'r', encoding='utf-8') as metadata_file:
            metadata = json.load(metadata_file)
        logging.debug(f"Task {task_id} metadata loaded: PID={metadata.get('pid')}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logging.error(f"Invalid metadata for task {task_id}: {exc}")
        return {
            'status': 'error',
            'error': f'Invalid metadata: {str(exc)}'
        }
    except Exception as exc:
        logging.error(f"Failed to read metadata for task {task_id}: {exc}")
        return {
            'status': 'error',
            'error': f'Failed to read metadata: {str(exc)}'
        }

    pid = metadata.get('pid')
    output_format = metadata.get('output_format', 'text')

    stdout_file = task_path.with_suffix('.stdout')
    stderr_file = task_path.with_suffix('.stderr')

    process_alive = is_process_alive(pid)

    is_running = False
    if stdout_file.exists() or stderr_file.exists():
        latest_mtime = max(
            stdout_file.stat().st_mtime if stdout_file.exists() else 0,
            stderr_file.stat().st_mtime if stderr_file.exists() else 0
        )
        idle_time = time.time() - latest_mtime
        logging.debug(f"Task {task_id} idle time: {idle_time:.1f}s, process_alive={process_alive}")

        if process_alive:
            is_running = True
        else:
            is_running = idle_time < 5
    else:
        is_running = process_alive

    if is_running:
        elapsed = time.time() - metadata['started_at']
        logging.debug(f"Task {task_id} is still running, elapsed={elapsed:.1f}s")
        return {
            'status': 'running',
            'task_id': task_id,
            'elapsed_seconds': int(elapsed),
            'command': metadata.get('command', 'N/A'),
            'working_dir': metadata.get('working_dir', 'N/A')
        }

    logging.debug(f"Task {task_id} completed, reading output files")
    try:
        stdout = safe_read_file(stdout_file)
        stderr = safe_read_file(stderr_file)
        result = extract_result_from_gemini_output(stdout, stderr, output_format)

        completed_at = max(
            stdout_file.stat().st_mtime if stdout_file.exists() else metadata['started_at'],
            stderr_file.stat().st_mtime if stderr_file.exists() else metadata['started_at']
        )

        metadata['status'] = 'completed'
        metadata['completed_at'] = completed_at
        try:
            with open(meta_file, 'w', encoding='utf-8') as metadata_file:
                json.dump(metadata, metadata_file, indent=2)
        except Exception as exc:
            logging.warning(f"Failed to update metadata for task {task_id}: {exc}")

        logging.info(f"Task {task_id} completed successfully, result length={len(result)}")
        return {
            'status': 'completed',
            'task_id': task_id,
            'result': result,
            'elapsed_seconds': int(completed_at - metadata['started_at']),
            'working_dir': metadata.get('working_dir', 'N/A')
        }
    except Exception as exc:
        logging.error(f"Failed to read output for task {task_id}: {exc}\n{traceback.format_exc()}")
        return {
            'status': 'error',
            'task_id': task_id,
            'error': f'Failed to read output: {str(exc)}'
        }


def call_gemini_sync(
    query: Optional[Union[str, Sequence[str]]] = None,
    working_dir: Optional[str] = None,
    sandbox: bool = False,
    yolo: bool = False,
    approval_mode: Optional[str] = None,
    experimental_acp: bool = False,
    allowed_mcp_server_names: Optional[Sequence[str]] = None,
    allowed_tools: Optional[Sequence[str]] = None,
    extensions: Optional[Sequence[str]] = None,
    include_directories: Optional[Sequence[str]] = None,
    output_format: Optional[str] = None,
    screen_reader: bool = False,
    debug: bool = False,
    additional_args: Optional[Sequence[str]] = None,
    timeout: Optional[int] = None
) -> str:
    """同步调用 Gemini CLI"""
    cmd = build_gemini_command(
        query=query,
        sandbox=sandbox,
        yolo=yolo,
        approval_mode=approval_mode,
        experimental_acp=experimental_acp,
        allowed_mcp_server_names=allowed_mcp_server_names,
        allowed_tools=allowed_tools,
        extensions=extensions,
        include_directories=include_directories,
        output_format=output_format,
        screen_reader=screen_reader,
        debug=debug,
        additional_args=additional_args
    )
    cwd = working_dir or os.getcwd()

    logging.info("Executing Gemini command synchronously in %s", cwd)
    try:
        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd
        )
        return extract_result_from_gemini_output(result.stdout, result.stderr, output_format)
    except subprocess.TimeoutExpired:
        logging.warning("Gemini CLI execution timed out")
        return "Error: Gemini CLI execution timed out"
    except Exception as exc:
        logging.error(f"Error calling Gemini CLI: {exc}\n{traceback.format_exc()}")
        return f"Error calling Gemini CLI: {str(exc)}"


def handle_request(request: Dict[str, Any]) -> None:
    """处理 MCP 请求"""
    method = request.get('method')
    request_id = request.get('id')
    params = request.get('params', {})

    if method == 'initialize':
        send_response({
            'jsonrpc': '2.0',
            'id': request_id,
            'result': {
                'protocolVersion': '2024-11-05',
                'capabilities': {'tools': {}},
                'serverInfo': {
                    'name': 'gemini-cli-mcp',
                    'version': '0.1.0'
                }
            }
        })
        return

    if method == 'notifications/initialized':
        logging.debug("Received initialized notification, no response needed")
        return

    if method == 'tools/list':
        send_response({
            'jsonrpc': '2.0',
            'id': request_id,
            'result': {
                'tools': [
                    {
                        'name': 'gemini_cli_execute',
                        'description': 'Execute Gemini CLI synchronously with configurable parameters. Supports both interactive and non-interactive prompts.',
                        'inputSchema': {
                            'type': 'object',
                            'properties': {
                                'query': {
                                    'description': 'Query or command arguments passed to Gemini CLI (positional arguments).',
                                    'oneOf': [
                                        {'type': 'string'},
                                        {'type': 'array', 'items': {'type': 'string'}}
                                    ]
                                },
                                'working_dir': {
                                    'type': 'string',
                                    'description': 'Working directory for the command (default: current directory)'
                                },
                                'sandbox': {
                                    'type': 'boolean',
                                    'description': 'Enable sandbox mode (--sandbox)',
                                    'default': False
                                },
                                'yolo': {
                                    'type': 'boolean',
                                    'description': 'Enable auto confirmation (--yolo)',
                                    'default': False
                                },
                                'approval_mode': {
                                    'type': 'string',
                                    'enum': ['default', 'auto_edit', 'yolo'],
                                    'description': 'Approval mode (--approval-mode)'
                                },
                                'experimental_acp': {
                                    'type': 'boolean',
                                    'description': 'Enable experimental ACP (--experimental-acp)',
                                    'default': False
                                },
                                'allowed_mcp_server_names': {
                                    'type': 'array',
                                    'items': {'type': 'string'},
                                    'description': 'Whitelisted MCP server names (--allowed-mcp-server-names)'
                                },
                                'allowed_tools': {
                                    'type': 'array',
                                    'items': {'type': 'string'},
                                    'description': 'Whitelisted tool names (--allowed-tools)'
                                },
                                'extensions': {
                                    'type': 'array',
                                    'items': {'type': 'string'},
                                    'description': 'Gemini CLI extensions (--extensions)'
                                },
                                'include_directories': {
                                    'type': 'array',
                                    'items': {'type': 'string'},
                                    'description': 'Additional directories (--include-directories)'
                                },
                                'output_format': {
                                    'type': 'string',
                                    'enum': ['text', 'json', 'stream-json'],
                                    'description': 'Output format (--output-format)'
                                },
                                'screen_reader': {
                                    'type': 'boolean',
                                    'description': 'Enable screen reader mode (--screen-reader)',
                                    'default': False
                                },
                                'debug': {
                                    'type': 'boolean',
                                    'description': 'Enable debug logging (--debug)',
                                    'default': False
                                },
                                'additional_args': {
                                    'type': 'array',
                                    'items': {'type': 'string'},
                                    'description': 'Additional CLI arguments appended verbatim'
                                },
                                'timeout': {
                                    'type': 'integer',
                                    'description': 'Timeout in seconds for synchronous execution'
                                }
                            }
                        }
                    },
                    {
                        'name': 'gemini_cli_execute_async',
                        'description': 'Start a Gemini CLI task in the background and return immediately with a task_id. Use gemini_cli_check_result to retrieve the result.',
                        'inputSchema': {
                            'type': 'object',
                            'properties': {
                                'query': {
                                    'description': 'Query or command arguments passed to Gemini CLI (positional arguments).',
                                    'oneOf': [
                                        {'type': 'string'},
                                        {'type': 'array', 'items': {'type': 'string'}}
                                    ]
                                },
                                'working_dir': {
                                    'type': 'string',
                                    'description': 'Working directory for the command (default: current directory)'
                                },
                                'sandbox': {
                                    'type': 'boolean',
                                    'description': 'Enable sandbox mode (--sandbox)',
                                    'default': False
                                },
                                'yolo': {
                                    'type': 'boolean',
                                    'description': 'Enable auto confirmation (--yolo)',
                                    'default': False
                                },
                                'approval_mode': {
                                    'type': 'string',
                                    'enum': ['default', 'auto_edit', 'yolo'],
                                    'description': 'Approval mode (--approval-mode)'
                                },
                                'experimental_acp': {
                                    'type': 'boolean',
                                    'description': 'Enable experimental ACP (--experimental-acp)',
                                    'default': False
                                },
                                'allowed_mcp_server_names': {
                                    'type': 'array',
                                    'items': {'type': 'string'},
                                    'description': 'Whitelisted MCP server names (--allowed-mcp-server-names)'
                                },
                                'allowed_tools': {
                                    'type': 'array',
                                    'items': {'type': 'string'},
                                    'description': 'Whitelisted tool names (--allowed-tools)'
                                },
                                'extensions': {
                                    'type': 'array',
                                    'items': {'type': 'string'},
                                    'description': 'Gemini CLI extensions (--extensions)'
                                },
                                'include_directories': {
                                    'type': 'array',
                                    'items': {'type': 'string'},
                                    'description': 'Additional directories (--include-directories)'
                                },
                                'output_format': {
                                    'type': 'string',
                                    'enum': ['text', 'json', 'stream-json'],
                                    'description': 'Output format (--output-format)'
                                },
                                'screen_reader': {
                                    'type': 'boolean',
                                    'description': 'Enable screen reader mode (--screen-reader)',
                                    'default': False
                                },
                                'debug': {
                                    'type': 'boolean',
                                    'description': 'Enable debug logging (--debug)',
                                    'default': False
                                },
                                'additional_args': {
                                    'type': 'array',
                                    'items': {'type': 'string'},
                                    'description': 'Additional CLI arguments appended verbatim'
                                }
                            }
                        }
                    },
                    {
                        'name': 'gemini_cli_check_result',
                        'description': 'Check the status of an async Gemini CLI task. Returns running/completed status and the result if available.',
                        'inputSchema': {
                            'type': 'object',
                            'properties': {
                                'task_id': {
                                    'type': 'string',
                                    'description': 'The task_id returned by gemini_cli_execute_async'
                                }
                            },
                            'required': ['task_id']
                        }
                    }
                ]
            }
        })
        return

    if method == 'tools/call':
        tool_name = params.get('name')
        arguments = params.get('arguments', {})

        if tool_name == 'gemini_cli_execute':
            result = call_gemini_sync(
                query=arguments.get('query'),
                working_dir=arguments.get('working_dir'),
                sandbox=arguments.get('sandbox', False),
                yolo=arguments.get('yolo', False),
                approval_mode=arguments.get('approval_mode'),
                experimental_acp=arguments.get('experimental_acp', False),
                allowed_mcp_server_names=arguments.get('allowed_mcp_server_names'),
                allowed_tools=arguments.get('allowed_tools'),
                extensions=arguments.get('extensions'),
                include_directories=arguments.get('include_directories'),
                output_format=arguments.get('output_format'),
                screen_reader=arguments.get('screen_reader', False),
                debug=arguments.get('debug', False),
                additional_args=arguments.get('additional_args'),
                timeout=arguments.get('timeout')
            )

            send_response({
                'jsonrpc': '2.0',
                'id': request_id,
                'result': {
                    'content': [{'type': 'text', 'text': result}]
                }
            })
            return

        if tool_name == 'gemini_cli_execute_async':
            task_id = start_gemini_async(
                query=arguments.get('query'),
                working_dir=arguments.get('working_dir'),
                sandbox=arguments.get('sandbox', False),
                yolo=arguments.get('yolo', False),
                approval_mode=arguments.get('approval_mode'),
                experimental_acp=arguments.get('experimental_acp', False),
                allowed_mcp_server_names=arguments.get('allowed_mcp_server_names'),
                allowed_tools=arguments.get('allowed_tools'),
                extensions=arguments.get('extensions'),
                include_directories=arguments.get('include_directories'),
                output_format=arguments.get('output_format'),
                screen_reader=arguments.get('screen_reader', False),
                debug=arguments.get('debug', False),
                additional_args=arguments.get('additional_args')
            )

            send_response({
                'jsonrpc': '2.0',
                'id': request_id,
                'result': {
                    'content': [{
                        'type': 'text',
                        'text': (
                            "Gemini CLI task started in background.\n"
                            f"Task ID: {task_id}\n\n"
                            f'Use gemini_cli_check_result(task_id="{task_id}") to retrieve the result.'
                        )
                    }]
                }
            })
            return

        if tool_name == 'gemini_cli_check_result':
            task_id = arguments.get('task_id')
            if not task_id:
                send_response({
                    'jsonrpc': '2.0',
                    'id': request_id,
                    'error': {
                        'code': -32602,
                        'message': 'task_id is required'
                    }
                })
                return

            status_info = check_task_status(task_id)

            if status_info['status'] == 'running':
                text = (
                    f"Task {task_id} is still running.\n"
                    f"Elapsed: {status_info['elapsed_seconds']}s\n"
                    f"Working Directory: {status_info.get('working_dir', 'N/A')}\n"
                    f"Command: {status_info.get('command', 'N/A')}"
                )
            elif status_info['status'] == 'completed':
                text = (
                    f"Task {task_id} completed in {status_info['elapsed_seconds']}s.\n"
                    f"Working Directory: {status_info.get('working_dir', 'N/A')}\n\n"
                    f"Result:\n{status_info.get('result', '')}"
                )
            else:
                text = status_info.get('error', 'Unknown error')

            send_response({
                'jsonrpc': '2.0',
                'id': request_id,
                'result': {
                    'content': [{'type': 'text', 'text': text}]
                }
            })
            return

        send_response({
            'jsonrpc': '2.0',
            'id': request_id,
            'error': {
                'code': -32601,
                'message': f'Unknown tool: {tool_name}'
            }
        })
        return

    send_response({
        'jsonrpc': '2.0',
        'id': request_id,
        'error': {
            'code': -32601,
            'message': f'Method not found: {method}'
        }
    })


def main():
    """主循环：从 stdin 读取请求，处理后写入 stdout"""
    logging.info("Main loop starting")
    logging.debug(f"stdin closed={sys.stdin.closed}, stdout closed={sys.stdout.closed}")
    request_count = 0
    try:
        for line in sys.stdin:
            request_count += 1
            logging.debug(f"Read line #{request_count}, length={len(line)}")
            line = line.strip()
            if not line:
                logging.debug("Empty line, skipping")
                continue

            try:
                request = json.loads(line)
                logging.debug(f"Received request #{request_count}: method={request.get('method')}, id={request.get('id')}")

                try:
                    handle_request(request)
                    logging.debug(f"Request {request.get('id')} handled successfully")
                except Exception as exc:
                    logging.error(f"handle_request failed: {exc}\n{traceback.format_exc()}")
                    send_response({
                        'jsonrpc': '2.0',
                        'id': request.get('id'),
                        'error': {
                            'code': -32603,
                            'message': f'Internal server error: {str(exc)}'
                        }
                    })

            except json.JSONDecodeError as exc:
                logging.warning(f"JSON parse error: {exc}")
                send_response({
                    'jsonrpc': '2.0',
                    'id': None,
                    'error': {
                        'code': -32700,
                        'message': f'Parse error: {str(exc)}'
                    }
                })

    except KeyboardInterrupt:
        logging.info("Gemini CLI MCP Server stopped by user (Ctrl+C)")
    except Exception as exc:
        logging.critical(f"Fatal error in main loop: {exc}\n{traceback.format_exc()}")
        raise
    finally:
        logging.info(f"=== Gemini CLI MCP Server Stopped === (processed {request_count} lines)")
        logging.debug(f"stdin closed={sys.stdin.closed}, stdout closed={sys.stdout.closed}")
        logging.info("Main loop exited normally (EOF on stdin)")


if __name__ == '__main__':
    main()

