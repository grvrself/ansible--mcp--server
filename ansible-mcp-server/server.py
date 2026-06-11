#!/usr/bin/env python3
"""Ansible MCP Server - 基于 FastMCP, Ansible MCP + SSH Agent.

运行: python server.py
Claude Desktop:
  {"mcpServers":{"ansible":{"command":"python","args":["C:\\Users\\grvr\\ansible-mcp-server\\server.py"]}}}
"""

from __future__ import annotations
import json, logging, os, sys
from pathlib import Path
import yaml

_PROJECT_DIR = Path(__file__).resolve().parent
if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))

from fastmcp import FastMCP
from ansible_runner import AnsibleRunner
from setup_helper import SetupHelper

LOG_FILE = _PROJECT_DIR / "mcp_server.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger("ansible-mcp-server")

_config: dict = {}
_runner: AnsibleRunner | None = None
_setup_helper: SetupHelper | None = None
_initialized: bool = False


def _init():
    global _config, _runner, _setup_helper, _initialized
    if _initialized:
        return
    config_path = Path(
        os.environ.get("ANSIBLE_MCP_CONFIG", _PROJECT_DIR / "config.local.yaml")
    )
    if not config_path.exists():
        config_path = _PROJECT_DIR / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        _config = yaml.safe_load(f)
    logger.info("Loaded config from %s", config_path)
    _runner = AnsibleRunner(_config)
    _setup_helper = SetupHelper(_config, _runner)
    try:
        _runner.connect()
        logger.info("SSH Ubuntu OK")
    except Exception as e:
        logger.warning("SSH fail(retry on call): %s", e)
    _initialized = True


def _fmt(label: str, ec: int, out: str, err: str) -> str:
    parts = [f"[cmd] {label}", f"[exit] {ec}"]
    if out:
        parts.append(f"[stdout]\n{out[:8000]}")
    if err:
        parts.append(f"[stderr]\n{err[:2000]}")
    return "\n\n".join(parts)
# ===================================================================
# FastMCP: @mcp.tool() decorator = auto schema + dispatch
# ===================================================================
mcp = FastMCP("ansible-mcp-server")


@mcp.tool()
def ansible_setup() -> str:
    """一键初始化Ansible: Ubuntu生成SSH密钥,分发公钥到所有VM(免密登录),创建inventory,验证连通性。首次使用前必须执行。"""
    _init()
    return json.dumps(_setup_helper.run_setup(), indent=2, ensure_ascii=False)


@mcp.tool()
def ansible_ping(target: str) -> str:
    """Ansible ping测试节点连通性。

    Args:
        target: 目标主机/组名, 如 all, centos, linux
    """
    _init()
    ok, out = _runner.ansible_ping(target)
    return f"{'OK' if ok else 'FAIL'}: {target}\n\n{out}"


@mcp.tool()
def ansible_run_command(target: str, command: str, become: bool = False) -> str:
    """在目标执行shell命令(Ad-hoc)。等价 ansible <target> -a '<command>'。

    Args:
        target: 目标主机/组名
        command: shell命令
        become: 是否sudo
    """
    _init()
    ec, out, err = _runner.ansible_command(target, command, become=become)
    return _fmt(f"ansible {target} -a '{command}'", ec, out, err)


@mcp.tool()
def ansible_run_module(target: str, module: str, args: str, become: bool = False) -> str:
    """调用Ansible模块。等价 ansible <target> -m <module> -a '<args>'。常用:apt,yum,service,copy,file,user,cron,git,shell。

    Args:
        target: 目标主机/组名
        module: 模块名 apt/yum/service等
        args: 参数如 name=nginx state=present
        become: 是否sudo
    """
    _init()
    ec, out, err = _runner.ansible_module(target, module, args, become=become)
    return _fmt(f"ansible {target} -m {module} -a '{args}'", ec, out, err)


@mcp.tool()
def ansible_run_playbook(playbook_content: str, target: str = "") -> str:
    """执行Ansible Playbook。提供YAML内容,自动上传执行。

    Args:
        playbook_content: Playbook完整YAML
        target: 可选限制目标(-l)
    """
    _init()
    ec, out, err = _runner.ansible_playbook(playbook_content, target=target or None)
    return _fmt("ansible-playbook", ec, out, err)


@mcp.tool()
def ansible_get_facts(target: str) -> str:
    """获取系统信息(OS/CPU/内存/磁盘/网络), Ansible setup模块。

    Args:
        target: 目标主机/组名
    """
    _init()
    _, out = _runner.ansible_facts(target)
    return out


@mcp.tool()
def ansible_list_inventory() -> str:
    """列出inventory中所有主机和分组。"""
    _init()
    return _runner.ansible_list_inventory()


@mcp.tool()
def ansible_add_host(name: str, host: str, user: str, groups: list[str] | None = None) -> str:
    """动态添加新节点到inventory。

    Args:
        name: 主机名
        host: IP地址
        user: SSH用户名
        groups: 所属组列表如["linux","web"]
    """
    _init()
    return _runner.ansible_add_host(name, host, user, groups)


@mcp.tool()
def ansible_exec_shell(command: str) -> str:
    """在Ubuntu控制节点直接执行shell(调试用途)。

    Args:
        command: 要执行的命令
    """
    _init()
    ec, out, err = _runner.execute(command)
    return _fmt(f"shell: {command}", ec, out, err)


if __name__ == "__main__":
    mcp.run()
